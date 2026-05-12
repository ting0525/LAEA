#include "uvgrtp_callback.h"

void rtp_frame_recv_callback(void* arg, uvg_rtp::frame::rtp_frame *frame){
    //std::cout << "Received RTP frame. Payload size: " << frame->payload_len << std::endl;
    RTPSession *session = (RTPSession*) (arg);
    session->copy_frame(frame);
    
    (void) uvgrtp::frame::dealloc_frame(frame);
};

void rtcp_recv_callback(uvgrtp::frame::rtcp_receiver_report *frame){
    std::cout << "-------- RTCP Receiver Report -------- "  << std::endl;
    for (auto& block : frame->report_blocks)
    {
        std::cout << "ssrc: "       << block.ssrc     << std::endl;
        std::cout << "fraction: "   << block.fraction << std::endl;
        std::cout << "lost: "       << block.lost     << std::endl;
        std::cout << "last_seq: "   << block.last_seq << std::endl;
        std::cout << "jitter: "     << block.jitter   << std::endl;
        std::cout << "lsr: "        << block.lsr      << std::endl;
        std::cout << "dlsr (jiffies): "  << uvgrtp::clock::jiffies_to_ms(block.dlsr)
                  << std::endl << std::endl;
    }
    std::cout << "-------- RTCP Receiver Report --------" << std::endl;
    delete frame;  
};

void rtcp_send_callback(uvgrtp::frame::rtcp_sender_report *frame){
    std::cout << "-------- RTCP sender report -------- " << std::endl;
    std::cout << "NTP msw: "        << frame->sender_info.ntp_msw   << std::endl;
    std::cout << "NTP lsw: "        << frame->sender_info.ntp_lsw   << std::endl;
    std::cout << "RTP timestamp: "  << frame->sender_info.rtp_ts    << std::endl;
    std::cout << "packet count: "   << frame->sender_info.pkt_cnt   << std::endl;
    std::cout << "byte count: "     << frame->sender_info.byte_cnt  << std::endl;

    for (auto& block : frame->report_blocks)
    {
        std::cout << "ssrc: "       << block.ssrc     << std::endl;
        std::cout << "fraction: "   << block.fraction << std::endl;
        std::cout << "lost: "       << block.lost     << std::endl;
        std::cout << "last_seq: "   << block.last_seq << std::endl;
        std::cout << "jitter: "     << block.jitter   << std::endl;
        std::cout << "lsr: "        << block.lsr      << std::endl;
        std::cout << "dlsr (jiffies): "  << uvgrtp::clock::jiffies_to_ms(block.dlsr)
                  << std::endl << std::endl;
    }
    std::cout << "-------- RTCP sender report --------"       << std::endl;
    delete frame;
};