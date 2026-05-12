#ifndef _uvgrtp_callback_H_
#define _uvgrtp_callback_H_

#include "Common.h"
#include "RTPSession.h"

// uvgrtp 有提供 polling api 可以自行 implement RTP RTCP frame 的接收

// 此處為使用 callback
// uvgrtp callbacks for processing RTP frame RTCP frame 
// uvgrtp callbacks

void rtp_frame_recv_callback(void* arg, uvg_rtp::frame::rtp_frame *frame);

void rtcp_recv_callback(uvgrtp::frame::rtcp_receiver_report *frame);

void rtcp_send_callback(uvgrtp::frame::rtcp_sender_report *frame);

#endif