# LAEA 專案架構圖

## 一、系統整體架構

```mermaid
graph TD
    %% ── 模擬環境 ──────────────────────────────────────
    subgraph SIM["☁ 模擬環境 (Gazebo + PX4 SITL)"]
        direction TB
        Gazebo["Gazebo\n(indoor_01.world)"]
        PX4["PX4 SITL\n(iris_d435_lidar)"]
        Gazebo <-->|"Gazebo plugin"| PX4
    end

    %% ── MAVLink 橋接 ─────────────────────────────────
    MAVROS["MAVROS\nUDP :14540 ↔ :14580"]
    PX4 -->|"UDP MAVLink"| MAVROS

    %% ── 飛行控制 ─────────────────────────────────────
    subgraph CTRL["✈ 飛行控制層"]
        GeoCtrl["Geometric Controller\n(mavros_controllers)"]
    end
    MAVROS -->|"/mavros/local_position/*\n/mavros/state"| GeoCtrl
    GeoCtrl -->|"/command/motor_speed"| MAVROS

    %% ── 感測器 Topics ────────────────────────────────
    subgraph SENSOR["📡 感測器 ROS Topics"]
        DepthImg["/camera/depth/image_raw\n32FC1 · 640×480"]
        ScanPC["/scan_pointcloud\n(LiDAR → PointCloud2)"]
        NavTopics["/mavros/local_position/odom\n/mavros/imu/data\n/mavros/global_position/raw/*"]
    end
    Gazebo -->|"深度相機"| DepthImg
    Gazebo -->|"2D LiDAR"| ScanPC
    MAVROS --> NavTopics

    %% ── RTP 傳輸層 ───────────────────────────────────
    subgraph RTP["📡 RTP 深度影像傳輸層\n(三種模式，擇一)"]
        RTPOut["/rtp/depth/image_raw"]
    end
    DepthImg -->|"sensor data"| RTP

    %% ── 地圖建構 ─────────────────────────────────────
    subgraph MAP["🗺 地圖建構"]
        Octomap["Octomap Server\n(scan_mapping.launch)"]
    end
    ScanPC --> Octomap

    %% ── LAEA 探索規劃 ────────────────────────────────
    subgraph PLAN["🧠 LAEA 探索規劃"]
        direction TB
        ExplMgr["Exploration Manager"]
        ActivePerc["Active Perception\n(Frontier Detection)"]
        PathSearch["Path Searching\n(A* / Kinodynamic)"]
        BsplineOpt["B-spline Optimizer\n(NLopt + LKH-TSP)"]

        ExplMgr --> ActivePerc --> PathSearch --> BsplineOpt
    end
    Octomap -->|"/octomap_full"| ExplMgr
    RTPOut  -->|"depth for planning"| ExplMgr
    BsplineOpt -->|"/planning/bspline"| GeoCtrl

    %% ── 資料收集 ─────────────────────────────────────
    subgraph DATA["📊 實驗資料收集"]
        ExpMgr["Experiment Manager\n(experiment_manager.py)"]
        KPI["SLAM KPI Logger\n(slam_kpi_logger.py)"]
        CSV["kpi_log_run_*.csv"]
        Summary["missions_summary.csv"]
        IsoForest["Isolation Forest\n(GPS 異常偵測)"]
    end
    ExplMgr -->|"mission start/stop"| KPI
    NavTopics -->|"GT/EST pose · GPS"| KPI
    KPI --> CSV --> Summary --> IsoForest

    %% ── Digital Twin ─────────────────────────────────
    subgraph TWIN["🔗 Digital Twin"]
        DittoBridge["Ditto Bridge\n(laea_ditto_bridge)"]
        Ditto["Eclipse Ditto\nlocalhost:8080/api/2"]
    end
    NavTopics -->|"pose · GPS · IMU\nnav_aux"| DittoBridge
    DittoBridge -->|"HTTP PUT\n(thing: laea:iris_0)"| Ditto

    %% ── AIoTtalk_plus (選配) ──────────────────────────
    subgraph AIoT["🌐 AIoTtalk_plus (選配)"]
        AIoTSrv["AIoTtalk_plus Server\n(SIPSignalingHandler\n+ RTPEstablisher\n+ RTPDevice)"]
        IoTtalk["IoTtalk Server\n140.114.77.93:9999\nProject: port 7788"]
        SIPSrv["SIP Server\n140.114.77.83"]
    end
    RTP <-->|"IoTtalk SDP 協商\n(SIP_SDP device)"| IoTtalk
    AIoTSrv <-->|"IoTtalk REST API"| IoTtalk
    AIoTSrv <-->|"SIP 信令"| SIPSrv
```

---

## 二、RTP 連線路徑（三種模式）

### 模式比較總覽

| | **Mode 1: nosip** | **Mode 2: iottalk** | **Mode 3: aiottalk_rtp** |
|---|---|---|---|
| 啟動方式 | 手動啟動 `rtp_gazebo` sender/receiver | 手動啟動 `rtp_gazebo` + `iottalk/sip.py` | `run_aiottalk_rtp.sh` |
| RTP 實現 | rtp_gazebo C++ | rtp_gazebo C++ | pybind11 uvgRTP (Python) |
| 信令 | 無（hardcoded port） | IoTtalk DAN push/pull | IoTtalk DAN push/pull |
| Sender port | 12000 | 協商後決定 | 12000 |
| Receiver port | 13000 | 協商後決定 | 13000 |
| Codec | Zdepth (zstd) | Zdepth (zstd) | Zdepth (zstd) |

---

### Mode 1 — nosip（直連，無信令）

```mermaid
flowchart LR
    subgraph Drone["🚁 無人機端"]
        Cam["/camera/depth/image_raw\n32FC1 · Gazebo"]
        Sender["RTPSender.cpp\n(rtp_gazebo ROS node)\nDepthImageCodec → Zdepth"]
    end

    subgraph Transport["🔌 uvgRTP UDP (loopback)"]
        Wire["UDP 127.0.0.1\nSender :12000 → Receiver :13000\nRCE_FRAGMENT_GENERIC"]
    end

    subgraph Server["💻 接收端"]
        Recv["RTPReceiver.cpp\n(rtp_gazebo ROS node)\nZdepth → float32"]
        Out["/rtp/depth/image_raw\n32FC1"]
    end

    Cam -->|"ROS callback\nfloat×1000→uint16"| Sender
    Sender -->|"RTP frame\npayload_type=97"| Wire
    Wire --> Recv --> Out
```

---

### Mode 2 — iottalk（C++ + IoTtalk 信令橋接）

```mermaid
flowchart LR
    subgraph Drone["🚁 無人機端"]
        Cam["/camera/depth/image_raw"]
        Sender["RTPSender.cpp\nuse_iottalk:=true"]
    end

    subgraph Signaling["📋 IoTtalk 信令 (iottalk/sip.py)"]
        SipPy["iottalk/sip.py\nROS node: SIP_SDP\nSIP_Sender · SIP_Receiver"]
        IoTSrv["IoTtalk Server\n140.114.77.93:9999"]
        SipPy <-->|"DAN.push/pull\nHTTP REST"| IoTSrv
    end

    subgraph ROSBridge["ROS Topics (SDP)"]
        SdpS["/sip_sender_sdp\n(a=1 12000 depth_stream...)"]
        SdpR["/sip_receiver_sdp\n(a=1 13000 depth_stream...)"]
    end

    subgraph Server["💻 接收端"]
        Recv["RTPReceiver.cpp\nuse_iottalk:=true"]
        Out["/rtp/depth/image_raw"]
    end

    Cam --> Sender
    SipPy -->|"SDP offer\n(Invite → OK)"| SdpS
    SipPy -->|"SDP answer\n(OK)"| SdpR
    SdpS -->|"Sender 讀取\n協商好的 port"| Sender
    SdpR -->|"Receiver 讀取\n協商好的 port"| Recv
    Sender -->|"uvgRTP UDP :12000→:13000\npayload_type=97 Zdepth"| Recv
    Recv --> Out
```

---

### Mode 3 — aiottalk_rtp（pybind11 + IoTtalk 信令，新）

```mermaid
flowchart LR
    subgraph Drone["🚁 無人機端 + 信令"]
        Cam["/camera/depth/image_raw"]
        Script["laea_aiottalk_rtp.py\nROS node: laea_aiottalk_rtp"]
        DAN["IoTtalk DAN\nSIP_SDP device\nSIP_Sender · SIP_Receiver"]
        PyRTPSend["pybind11 RTPSession\n(sender)\nlocal:12000 → remote:13000"]
        PyRTPRecv["pybind11 RTPSession\n(receiver)\nlocal:13000"]
    end

    subgraph Lib["📦 AIoTtalk_plus_Lib"]
        PyBind["MyTool_pybind11.so\n(Python 3.8)"]
        UvgRTP["uvgRTP\n(C++ library)"]
        Zdepth["DepthImageCodec\n(Zdepth/zstd)"]
        PyBind --> UvgRTP --> Zdepth
    end

    subgraph IoTtalkSrv["IoTtalk 信令"]
        IoT["IoTtalk Server\n140.114.77.93:9999"]
    end

    subgraph Out["📥 輸出"]
        RTPOut["/rtp/depth/image_raw\n32FC1"]
    end

    Cam -->|"imgmsg_to_cv2\nnp.float32"| Script
    Script --> DAN
    DAN <-->|"DAN.push SDP invite\nDAN.pull SDP answer\nHTTP REST"| IoT
    Script --> PyRTPSend
    Script --> PyRTPRecv
    PyRTPSend --> PyBind
    PyRTPRecv --> PyBind
    PyRTPSend -->|"uvgRTP UDP\n:12000 → :13000\npayload_type=97"| PyRTPRecv
    PyRTPRecv -->|"cv2_to_imgmsg\n32FC1"| RTPOut
```

---

## 三、AIoTtalk_plus 完整 SIP/IoTtalk 信令流程

> 此為 AIoTtalk_plus server 所支援的**完整 SIP 鏈路**（需 SIPSignalingHandler 啟動）。
> Mode 3 目前使用簡化版（直接 DAN push/pull，無真實 SIP）。

```mermaid
sequenceDiagram
    participant SUA as SUA (無人機端)<br/>7001@140.114.77.83
    participant SIPSrv as SIP Server<br/>140.114.77.83
    participant SIPHandler as SIPSignalingHandler<br/>devicetest1@140.114.77.83
    participant IoT as IoTtalk Server<br/>140.114.77.93:9999
    participant Establisher as RTPEstablisher<br/>(Flask :3003)
    participant RTPDev as RTPDevice<br/>(receiver.py)

    SUA->>SIPSrv: SIP INVITE + SDP offer<br/>(depth_stream, sendonly, port 12000)
    SIPSrv->>SIPHandler: 轉發 INVITE
    SIPHandler->>IoT: PUT SDPOffer-I<br/>(SDP offer JSON)
    IoT-->>Establisher: pull SDPOffer-O<br/>(SDP offer)
    Establisher->>IoT: PUT ControlRequest-I<br/>(connect, sip_device_params)
    IoT-->>RTPDev: pull ControlRequest-O<br/>(connect request)
    RTPDev->>RTPDev: start receiver.py<br/>(pybind11 RTPSession<br/>recvonly, port 14002)
    RTPDev->>IoT: PUT ControlResponse-I<br/>(rtp_device_params)
    IoT-->>Establisher: pull ControlResponse-O<br/>(RTP params)
    Establisher->>IoT: PUT SDPAnswer-I<br/>(SDP answer JSON)
    IoT-->>SIPHandler: pull SDPAnswer-O
    SIPHandler->>SIPSrv: 200 OK + SDP answer
    SIPSrv->>SUA: 200 OK + SDP answer<br/>(recvonly, port 14002)

    Note over SUA,RTPDev: RTP session 建立完成

    SUA-->>RTPDev: uvgRTP depth frames<br/>Zdepth · payload_type=97<br/>:12000 → :14002
```

---

## 四、元件與目錄對應

| 元件 | 目錄 | 語言 |
|---|---|---|
| Gazebo 模擬環境 | `px4_gazebo/` | Launch/XML |
| 飛行控制器 | `mavros_controllers/geometric_controller/` | C++ |
| RTP 傳輸（Mode 1/2） | `rtp/`, `rtp_gazebo/` | C++ (ROS node) |
| RTP 傳輸（Mode 3） | `laea_aiottalk_rtp.py` | Python (ROS node) |
| RTP pybind11 library | `AIoTtalk_plus/AIoTtalk_plus_Lib/RTP/` | C++ + pybind11 |
| uvgRTP | `3rd/uvgRTP/`, `AIoTtalk_plus_Lib/3rd/uvgRTP/` | C++ |
| Octomap 地圖 | `laea_planner/octomap_mapping/` | C++ |
| 探索規劃 | `laea_planner/exploration_manager/` | C++ |
| IoTtalk DAN | `iottalk/DAN.py` | Python |
| IoTtalk SIP 橋接 | `iottalk/sip.py` | Python (ROS node) |
| AIoTtalk_plus Server | `AIoTtalk_plus/AIoTtalk_Server/AIoTtalk_plus/` | Python |
| AIoTtalk_plus SUA | `AIoTtalk_plus/SUA/rtp_SUA/` | Python |
| AIoTtalk_plus AUA | `AIoTtalk_plus/AUA/` | Python |
| Ditto Bridge | `laea_ditto_bridge/` | Python (ROS node) |
| 實驗管理 | `laea_twin_tools/scripts/` | Python |
| ML 異常偵測 | `train_isolation_forest.ipynb`, `data/` | Python/Jupyter |
