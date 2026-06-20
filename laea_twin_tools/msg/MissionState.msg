uint8 NORMAL=0
uint8 DEGRADED=1
uint8 CRITICAL=2

uint8 FEEDBACK_NONE=0
uint8 FEEDBACK_ALERT=1
uint8 FEEDBACK_SLOW_DOWN=2
uint8 FEEDBACK_HOVER=3

uint32 REASON_LOCALIZATION=1
uint32 REASON_PERCEPTION=2
uint32 REASON_PLANNER=4
uint32 REASON_FLIGHT_SAFETY=8
uint32 REASON_MODEL=16

std_msgs/Header header

uint8 localization_level
uint8 perception_level
uint8 planner_level
uint8 flight_safety_level
uint8 overall_level

float64 localization_score
float64 perception_score
float64 planner_score
float64 flight_safety_score

string detector_name
float64 anomaly_score
uint32 reason_bits
uint8 recommended_feedback
bool hard_safety_latched
string summary
