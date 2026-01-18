#include "Stream.h"

int Stream::send_data(struct Data *data){
    if (!media_stream) {
        std::cout << "RTP push_frame failed: media_stream is null" << std::endl;
        return -1;
    }

    // 關鍵：呼叫端會在 send_data() 後 destroy_data()，因此必須讓 uvgRTP 複製 payload
    // 否則在非同步送出時會出現 use-after-free，進而導致 "transmit failed" 或 segfault。
    int ret = media_stream->push_frame(data->buffer, data->size, RTP_COPY);
    if (ret != RTP_OK){
        std::cout << "RTP push_frame transmit failed" << std::endl;
        return -1;
    }
    return 0;
};

struct Data* Stream::get_data(){
    struct Data *data = stream_buffer.get();
    return data;
}
