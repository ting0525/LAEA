#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import math
import signal
import subprocess
import threading
import rospy

from geometry_msgs.msg import PoseStamped
from gazebo_msgs.msg import ModelStates
from rosgraph_msgs.msg import Log as RosLog
from laea_twin_tools.msg import AttackCommand, AttackStatus, SupervisorCommand


MANIFEST_FIELDS = [
    "manifest_version",
    "run_id",
    "scenario",
    "transport_mode",
    "world_name",
    "started_at_s",
    "ended_at_s",
    "duration_s",
    "outcome",
    "log_retained",
    "log_deleted",
    "delete_reason",
    "attack_source",
    "attack_mode",
    "attack_severity",
    "attack_seed",
    "attack_scheduled_onset_s",
    "attack_actual_onset_s",
    "hover_reason_bits",
    "hover_hard_latched",
    "hover_reason",
]


def annotate_csv_outcome(path, outcome):
    """Rewrite a completed run with a stable outcome value on each sample."""
    temp_path = path + ".outcome.tmp"
    with open(path, "r", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        if "mission_outcome" not in fieldnames:
            fieldnames.append("mission_outcome")
        with open(temp_path, "w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                row["mission_outcome"] = outcome
                writer.writerow(row)
    os.replace(temp_path, path)


def append_manifest_row(path, row):
    """Append one low-volume run summary, creating a stable header if needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    needs_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=MANIFEST_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
        target.flush()
        os.fsync(target.fileno())


class ExperimentManager:
    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def __init__(self):
        rospy.init_node("experiment_manager", anonymous=False)

        # ----------------------------
        # Orchestration params
        # ----------------------------
        self.num_runs = int(rospy.get_param("~num_runs", 1))
        self.sleep_between_runs_s = float(rospy.get_param("~sleep_between_runs_s", 2.0))

        # Trigger
        self.start_topic = rospy.get_param("~start_topic", "/traj_start_trigger")
        self.start_frame_id = rospy.get_param("~start_frame_id", "map")
        self.start_pub = rospy.Publisher(self.start_topic, PoseStamped, queue_size=1, latch=True)

        # ----------------------------
        # Success token (唯一成功標準)
        # ----------------------------
        self._run_start_time = None
        self._finish_seen = False
        self._finish_time = None

        self.rosout_topic = rospy.get_param("~rosout_topic", "/rosout_agg")
        self.finish_token = rospy.get_param("~finish_token", "finish exploration.")
        
        self.finish_node_name = rospy.get_param("~finish_node_name", "")  # "" = 不限制
        rospy.Subscriber(self.rosout_topic, RosLog, self._rosout_cb, queue_size=200)

        # ----------------------------
        # Fail detection (GT vs EST)
        # ----------------------------
        self.model_name = rospy.get_param("~model_name", "iris_0")
        self.fail_error_m = float(rospy.get_param("~fail_error_m", 10.0))
        self.fail_hold_s = float(rospy.get_param("~fail_hold_s", 1.0))

        # Timeout: 沒 finish 一律視為非成功（刪檔）
        self.max_duration_s = float(rospy.get_param("~max_duration_s", 900.0))

        # ----------------------------
        # Logger control
        # ----------------------------
        self.output_dir = rospy.get_param(
            "~output_dir",
            rospy.get_param(
                "/slam_kpi_logger/output_dir",
                "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs"
            )
        )
        self.logger_script = rospy.get_param(
            "~logger_script",
            "/home/tim/laea/src/LAEA/laea_twin_tools/scripts/slam_kpi_logger.py"
        )
        # Optional fallback for legacy workflow
        self.use_roslaunch_logger = self._as_bool(
            rospy.get_param("~use_roslaunch_logger", False)
        )
        self.logger_launch = rospy.get_param(
            "~logger_launch",
            "/home/tim/laea/src/LAEA/laea_twin_tools/launch/slam_kpi_logger.launch"
        )
        self.scenario = str(rospy.get_param("~scenario", "normal"))
        self.transport_mode = str(rospy.get_param("~transport_mode", "unspecified"))
        self.world_name = str(rospy.get_param("~world_name", "unknown"))
        self.depth_topic = str(rospy.get_param("~depth_topic", "/rtp/depth/image_raw"))
        self.depth_stale_threshold_s = float(rospy.get_param("~depth_stale_threshold_s", 0.25))

        # Dataset governance
        self.delete_on_non_success = self._as_bool(rospy.get_param("~delete_on_non_success", True))
        self.manifest_path = str(
            rospy.get_param(
                "~manifest_path", os.path.join(self.output_dir, "run_manifest.csv")
            )
        )

        # Mission-aware terminal handling. A Hover published before the mission
        # trigger is ignored so a stale latched command cannot terminate a run.
        self.terminate_on_hover = self._as_bool(
            rospy.get_param("~terminate_on_hover", True)
        )
        self.supervisor_command_topic = str(
            rospy.get_param(
                "~supervisor_command_topic", "/laea/supervisor/command"
            )
        )
        self.attack_command_topic = str(
            rospy.get_param("~attack_command_topic", "/laea/attack/command")
        )
        self.attack_status_topic = str(
            rospy.get_param("~attack_status_topic", "/laea/attack/status")
        )

        # ----------------------------
        # Persistent Run ID (解決覆蓋的關鍵)
        # ----------------------------
        # 序號檔：跨重啟唯一遞增，確保永不覆蓋
        self.run_seq_file = rospy.get_param("~run_seq_file", os.path.join(self.output_dir, "run_seq.txt"))

        # ----------------------------
        # Data inputs
        # ----------------------------
        self.gt_xyz = None
        self.est_xyz = None

        # Callback-visible state must exist before subscribers are registered,
        # because latched ROS messages may invoke callbacks immediately.
        self._state_lock = threading.Lock()
        self._mission_trigger_time = None
        self._fail_start_time = None
        self._hover_seen = False
        self._hover_time = None
        self._hover_reason_bits = 0
        self._hover_hard_latched = False
        self._hover_reason = ""
        self._attack_info = {
            "source": "",
            "mode": "",
            "severity": "",
            "seed": "",
            "scheduled_start_s": 0.0,
            "actual_onset_s": 0.0,
        }

        rospy.Subscriber("/gazebo/model_states", ModelStates, self._gt_cb, queue_size=10)
        rospy.Subscriber("/mavros/local_position/pose", PoseStamped, self._est_cb, queue_size=50)
        rospy.Subscriber(
            self.supervisor_command_topic,
            SupervisorCommand,
            self._supervisor_command_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            self.attack_command_topic,
            AttackCommand,
            self._attack_command_cb,
            queue_size=10,
        )
        rospy.Subscriber(
            self.attack_status_topic,
            AttackStatus,
            self._attack_status_cb,
            queue_size=20,
        )

        self._logger_proc = None
        self._cached_log_path = ""

    # ----------------------------
    # Callbacks
    # ----------------------------
    def _rosout_cb(self, msg: RosLog):
        if self._run_start_time is None:
            return
        if msg.header.stamp < self._run_start_time:
            return
        if self.finish_node_name and (msg.name != self.finish_node_name):
            return
        if self.finish_token in (msg.msg or ""):
            self._finish_seen = True
            self._finish_time = msg.header.stamp

    def _gt_cb(self, msg: ModelStates):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            return
        p = msg.pose[idx].position
        self.gt_xyz = (p.x, p.y, p.z)

    def _est_cb(self, msg: PoseStamped):
        p = msg.pose.position
        self.est_xyz = (p.x, p.y, p.z)

    def _supervisor_command_cb(self, msg: SupervisorCommand):
        if not self.terminate_on_hover or msg.level != SupervisorCommand.HOVER:
            return

        received_at = rospy.Time.now()
        event_time = (
            msg.header.stamp
            if msg.header.stamp and msg.header.stamp.to_sec() > 0.0
            else received_at
        )
        with self._state_lock:
            if self._mission_trigger_time is None:
                return
            if event_time < self._mission_trigger_time:
                return
            if self._hover_seen:
                return
            self._hover_seen = True
            self._hover_time = event_time
            self._hover_reason_bits = int(msg.reason_bits)
            self._hover_hard_latched = bool(msg.hard_latched)
            self._hover_reason = str(msg.reason)

    def _attack_command_cb(self, msg: AttackCommand):
        with self._state_lock:
            self._attack_info.update(
                {
                    "source": str(msg.source),
                    "mode": str(msg.mode),
                    "severity": str(msg.severity),
                    "seed": int(msg.seed),
                    "scheduled_start_s": msg.scheduled_start.to_sec(),
                }
            )

    def _attack_status_cb(self, msg: AttackStatus):
        with self._state_lock:
            self._attack_info.update(
                {
                    "source": str(msg.source),
                    "mode": str(msg.mode),
                    "severity": str(msg.severity),
                }
            )
            onset_s = msg.actual_onset.to_sec()
            if onset_s > 0.0:
                self._attack_info["actual_onset_s"] = onset_s

    # ----------------------------
    # Helpers
    # ----------------------------
    def _compute_e_pos(self):
        if self.gt_xyz is None or self.est_xyz is None:
            return None
        dx = self.gt_xyz[0] - self.est_xyz[0]
        dy = self.gt_xyz[1] - self.est_xyz[1]
        dz = self.gt_xyz[2] - self.est_xyz[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def _wait_ready(self, timeout_s=60.0):
        """最小 readiness gate：確保 GT/EST 都有資料"""
        t0 = rospy.Time.now()
        rate = rospy.Rate(10)
        while not rospy.is_shutdown():
            if self.gt_xyz is not None and self.est_xyz is not None:
                return True
            if (rospy.Time.now() - t0).to_sec() > timeout_s:
                return False
            rate.sleep()
        return False

    def _publish_start_trigger(self):
        msg = PoseStamped()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = self.start_frame_id
        # 位置內容依你 waypoint_generator 行為；大多數情況 frame_id 正確即足夠
        msg.pose.position.x = 0.0
        msg.pose.position.y = 0.0
        msg.pose.position.z = 0.0
        msg.pose.orientation.w = 1.0
        with self._state_lock:
            self._mission_trigger_time = msg.header.stamp
        self.start_pub.publish(msg)

    def _next_global_run_id(self) -> str:
        """跨重啟的全域 run 序號：避免永遠 run_001 覆蓋"""
        os.makedirs(self.output_dir, exist_ok=True)

        n = 0
        if os.path.isfile(self.run_seq_file):
            try:
                with open(self.run_seq_file, "r") as f:
                    n = int((f.read() or "0").strip())
            except Exception:
                n = 0

        n += 1

        # 原子更新：避免寫到一半中斷造成 seq 壞掉
        tmp_path = self.run_seq_file + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(str(n))
        os.replace(tmp_path, self.run_seq_file)

        return f"run_{n:03d}"

    def _start_logger(self, run_id: str):
        """
        每個 run 啟動一次 logger，並把 run_id 帶進去
        讓 logger 輸出：kpi_log_<run_id>.csv
        """
        if self._logger_proc is not None and self._logger_proc.poll() is None:
            rospy.logwarn("Logger already running, terminating previous instance.")
            self._stop_logger()

        # Set params explicitly so direct python launch behaves like launch file.
        self._cached_log_path = os.path.join(self.output_dir, f"kpi_log_{run_id}.csv")
        rospy.set_param("/slam_kpi_logger/output_dir", self.output_dir)
        rospy.set_param("/slam_kpi_logger/output_name", f"kpi_log_{run_id}")
        rospy.set_param("/slam_kpi_logger/run_id", run_id)
        rospy.set_param("/slam_kpi_logger/scenario", self.scenario)
        rospy.set_param("/slam_kpi_logger/transport_mode", self.transport_mode)
        rospy.set_param("/slam_kpi_logger/world_name", self.world_name)
        rospy.set_param("/slam_kpi_logger/depth_topic", self.depth_topic)
        rospy.set_param("/slam_kpi_logger/depth_stale_threshold_s", self.depth_stale_threshold_s)

        if self.use_roslaunch_logger:
            cmd = ["roslaunch", self.logger_launch]
            rospy.loginfo(f"[RUN {run_id}] start logger (roslaunch): {' '.join(cmd)}")
        else:
            cmd = ["python3", self.logger_script]
            rospy.loginfo(f"[RUN {run_id}] start logger (python): {' '.join(cmd)}")

        self._logger_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )

        # 給 logger 時間 set /laea_twin/current_log_path
        rospy.sleep(1.0)

        # 可選：快速稽核 current_log_path
        try:
            path = rospy.get_param("/laea_twin/current_log_path", "")
            if not path:
                rospy.logwarn(f"[RUN {run_id}] current_log_path is empty after logger start.")
            else:
                rospy.loginfo(f"[RUN {run_id}] current_log_path={path}")
        except Exception:
            rospy.logwarn(f"[RUN {run_id}] unable to read /laea_twin/current_log_path after logger start.")

    def _stop_logger(self):
        if self._logger_proc is None:
            return
        if self._logger_proc.poll() is not None:
            self._logger_proc = None
            return
        try:
            os.killpg(os.getpgid(self._logger_proc.pid), signal.SIGINT)
        except Exception:
            pass
        try:
            self._logger_proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._logger_proc.pid), signal.SIGKILL)
            except Exception:
                pass
        self._logger_proc = None

    def _delete_current_log(self, reason: str):
        if not self.delete_on_non_success:
            return False

        path = self._current_log_path()
        if not path:
            rospy.logwarn(f"[DELETE] ({reason}) current_log_path param not set; skip delete.")
            return False

        if os.path.isfile(path):
            try:
                os.remove(path)
                rospy.logwarn(f"[DELETE] ({reason}) removed log: {path}")
                return True
            except Exception as e:
                rospy.logerr(f"[DELETE] ({reason}) failed to remove {path}: {e}")
        else:
            rospy.logwarn(f"[DELETE] ({reason}) file not found: {path}")
        return False

    def _current_log_path(self):
        if self._cached_log_path:
            return self._cached_log_path
        try:
            return rospy.get_param("/laea_twin/current_log_path", "")
        except Exception:
            return ""

    def _annotate_current_log(self, outcome):
        path = self._current_log_path()
        if not path or not os.path.isfile(path):
            rospy.logwarn(f"[RUN] cannot annotate outcome={outcome}; log file not found: {path}")
            return
        try:
            annotate_csv_outcome(path, outcome)
            rospy.loginfo(f"[RUN] annotated mission_outcome={outcome}: {path}")
        except Exception as error:
            rospy.logerr(f"[RUN] failed to annotate mission_outcome for {path}: {error}")

    # ----------------------------
    # Run lifecycle
    # ----------------------------
    def _reset_run_flags(self):
        self._run_start_time = rospy.Time.now()
        self._finish_seen = False
        self._finish_time = None
        self._fail_start_time = None
        with self._state_lock:
            self._mission_trigger_time = None
            self._hover_seen = False
            self._hover_time = None
            self._hover_reason_bits = 0
            self._hover_hard_latched = False
            self._hover_reason = ""
            self._attack_info["actual_onset_s"] = 0.0

    def _terminal_feedback_outcome(self):
        with self._state_lock:
            hover_seen = self._hover_seen
            hover_time = self._hover_time

        if not self._finish_seen and not hover_seen:
            return None
        if self._finish_seen and not hover_seen:
            return "SUCCESS_FINISH"
        if hover_seen and not self._finish_seen:
            return "SAFETY_HOVER"
        if hover_time is not None and self._finish_time is not None:
            return (
                "SAFETY_HOVER"
                if hover_time < self._finish_time
                else "SUCCESS_FINISH"
            )
        return "SAFETY_HOVER"

    @staticmethod
    def _relative_time_s(event_time_s, start_time_s):
        if event_time_s <= 0.0 or start_time_s <= 0.0 or event_time_s < start_time_s:
            return ""
        return round(event_time_s - start_time_s, 6)

    def _append_run_manifest(self, run_id, outcome, ended_at, log_deleted):
        with self._state_lock:
            trigger_time = self._mission_trigger_time
            attack_info = dict(self._attack_info)
            hover_reason_bits = self._hover_reason_bits
            hover_hard_latched = self._hover_hard_latched
            hover_reason = self._hover_reason

        started_at = trigger_time or self._run_start_time
        started_at_s = started_at.to_sec() if started_at is not None else 0.0
        ended_at_s = ended_at.to_sec()
        log_path = self._current_log_path()
        log_retained = bool(log_path and os.path.isfile(log_path))
        delete_reason = outcome if outcome != "SUCCESS_FINISH" else ""

        row = {
            "manifest_version": 1,
            "run_id": run_id,
            "scenario": self.scenario,
            "transport_mode": self.transport_mode,
            "world_name": self.world_name,
            "started_at_s": f"{started_at_s:.6f}",
            "ended_at_s": f"{ended_at_s:.6f}",
            "duration_s": f"{max(ended_at_s - started_at_s, 0.0):.6f}",
            "outcome": outcome,
            "log_retained": str(log_retained).lower(),
            "log_deleted": str(bool(log_deleted)).lower(),
            "delete_reason": delete_reason,
            "attack_source": attack_info["source"],
            "attack_mode": attack_info["mode"],
            "attack_severity": attack_info["severity"],
            "attack_seed": attack_info["seed"],
            "attack_scheduled_onset_s": self._relative_time_s(
                float(attack_info["scheduled_start_s"]), started_at_s
            ),
            "attack_actual_onset_s": self._relative_time_s(
                float(attack_info["actual_onset_s"]), started_at_s
            ),
            "hover_reason_bits": hover_reason_bits if outcome == "SAFETY_HOVER" else "",
            "hover_hard_latched": (
                str(hover_hard_latched).lower()
                if outcome == "SAFETY_HOVER"
                else ""
            ),
            "hover_reason": hover_reason if outcome == "SAFETY_HOVER" else "",
        }
        append_manifest_row(self.manifest_path, row)
        rospy.loginfo(
            "[RUN %s] appended outcome=%s to manifest: %s",
            run_id,
            outcome,
            self.manifest_path,
        )

    def _monitor_one_run(self, run_id: str):
        """
        Return outcome:
          - SUCCESS_FINISH
          - SAFETY_HOVER
          - FAIL_SLAM
          - TIMEOUT_NO_FINISH
          - ABORTED
        """
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            # 1) Finish/Hover: whichever happened first is the terminal outcome.
            terminal_outcome = self._terminal_feedback_outcome()
            if terminal_outcome == "SUCCESS_FINISH":
                rospy.loginfo(f"[RUN {run_id}] SUCCESS_FINISH at {self._finish_time.to_sec():.3f}")
                return "SUCCESS_FINISH"
            if terminal_outcome == "SAFETY_HOVER":
                with self._state_lock:
                    hover_time = self._hover_time
                    hover_reason = self._hover_reason
                rospy.logwarn(
                    "[RUN %s] SAFETY_HOVER at %.3f reason=%s",
                    run_id,
                    hover_time.to_sec() if hover_time is not None else 0.0,
                    hover_reason,
                )
                return "SAFETY_HOVER"

            # 2) fail: e_pos hold
            epos = self._compute_e_pos()
            if epos is not None and epos > self.fail_error_m:
                if self._fail_start_time is None:
                    self._fail_start_time = rospy.Time.now()
                else:
                    held = (rospy.Time.now() - self._fail_start_time).to_sec()
                    if held >= self.fail_hold_s:
                        rospy.logerr(f"[RUN {run_id}] FAIL_SLAM e_pos={epos:.2f}m held={held:.2f}s")
                        return "FAIL_SLAM"
            else:
                self._fail_start_time = None

            # 3) timeout: no finish
            elapsed = (rospy.Time.now() - self._run_start_time).to_sec()
            if elapsed >= self.max_duration_s:
                rospy.logwarn(f"[RUN {run_id}] TIMEOUT_NO_FINISH elapsed={elapsed:.1f}s")
                return "TIMEOUT_NO_FINISH"

            try:
                rate.sleep()
            except rospy.ROSInterruptException:
                return "ABORTED"

        return "ABORTED"

    def _finalize_run(self, run_id, outcome, ended_at):
        # Stop logger before annotating or deleting its output.
        self._stop_logger()
        try:
            self._annotate_current_log(outcome)
        except Exception as exc:
            rospy.logwarn(f"[RUN {run_id}] annotation failed: {exc}")

        # Dataset governance: only SUCCESS_FINISH keeps the high-frequency CSV.
        log_deleted = False
        if outcome != "SUCCESS_FINISH":
            log_deleted = self._delete_current_log(reason=outcome)
        else:
            rospy.loginfo(f"[RUN {run_id}] kept log (SUCCESS_FINISH).")

        try:
            self._append_run_manifest(run_id, outcome, ended_at, log_deleted)
        except Exception as exc:
            rospy.logerr(f"[RUN {run_id}] failed to append manifest: {exc}")
        self._cached_log_path = ""

    def run(self):
        rospy.loginfo(
            f"[experiment_manager] num_runs={self.num_runs}, output_dir={self.output_dir}, "
            f"scenario={self.scenario}, transport={self.transport_mode}, world={self.world_name}"
        )
        ok = self._wait_ready(timeout_s=60.0)
        if not ok:
            rospy.logerr("[experiment_manager] Inputs not ready: missing GT/EST. Abort.")
            return

        for _ in range(self.num_runs):
            run_id = self._next_global_run_id()
            rospy.loginfo(f"========== RUN {run_id} ==========")

            self._reset_run_flags()
            outcome = "ABORTED"
            interrupted = False
            try:
                # Start logger before the trigger to avoid losing early samples.
                self._start_logger(run_id)
                self._publish_start_trigger()
                outcome = self._monitor_one_run(run_id)
            except (rospy.ROSInterruptException, KeyboardInterrupt):
                interrupted = True
                outcome = "ABORTED"
                rospy.logwarn(f"[RUN {run_id}] interrupted; finalizing as ABORTED.")
            finally:
                self._finalize_run(run_id, outcome, rospy.Time.now())

            if interrupted or rospy.is_shutdown():
                break
            rospy.sleep(self.sleep_between_runs_s)

        rospy.loginfo("[experiment_manager] All runs completed.")


if __name__ == "__main__":
    try:
        mgr = ExperimentManager()
        mgr.run()
    except rospy.ROSInterruptException:
        pass
