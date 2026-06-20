uint8 NONE=0
uint8 ALERT=1
uint8 SLOW_DOWN=2
uint8 HOVER=3

std_msgs/Header header

uint8 level
float64 speed_scale
bool hold_position
geometry_msgs/Point hold_point
float64 hold_yaw
bool hard_latched
uint32 reason_bits
string reason
