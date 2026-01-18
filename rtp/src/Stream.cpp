#include "Stream.h"

int Stream::send_data(struct Data *data){
    if (data == nullptr || data->buffer == nullptr || data->size == 0) {
        std::cout << "RTP push_frame skipped (empty data)"
                  << " stream_id=" << id
                  << " name=" << name
                  << std::endl;
        return -1;
    }

    int ret = media_stream->push_frame(data->buffer, data->size, RTP_NO_FLAGS);
    if (ret != RTP_OK){
        std::cout << "RTP push_frame transmit failed"
                  << " stream_id=" << id
                  << " name=" << name
                  << " size=" << data->size
                  << " ret=" << ret
                  << std::endl;
        return -1;
    }
    return 0;
};

struct Data* Stream::get_data(){
    struct Data *data = stream_buffer.get();
    return data;
}
