#include "VideoCodec.h"

VideoCodec::VideoCodec(){
    image_width = 640;
    image_height = 480;
    codec_id = AV_CODEC_ID_H264; 
    codec_type = AVMEDIA_TYPE_VIDEO; 
    pix_fmt = AV_PIX_FMT_YUV420P; 
    sws_pix_fmt = AV_PIX_FMT_BGR24;
};

VideoCodec::VideoCodec(
    int _image_width, int _image_height):
    image_width(_image_width), image_height(_image_height)
{
    codec_id = AV_CODEC_ID_H264; 
    codec_type = AVMEDIA_TYPE_VIDEO; 
    pix_fmt = AV_PIX_FMT_YUV420P; 
    sws_pix_fmt = AV_PIX_FMT_BGR24;
};

VideoCodec::VideoCodec(
    int _image_width, 
    int _image_height, 
    AVCodecID _codec_id, 
    AVMediaType _codec_type, 
    AVPixelFormat _pix_fmt, 
    AVPixelFormat _sws_pix_fmt
):image_width(_image_width),
image_height(_image_height),
codec_id(_codec_id),
pix_fmt(_pix_fmt),
sws_pix_fmt(_sws_pix_fmt)
{};

VideoCodec::~VideoCodec(){};

int VideoCodec::init(){

    int ret;
    param = NULL;

    //Set up the Video Compression arguments
    av_dict_set(&param, "qp", "20", 0);
    av_dict_set(&param, "preset", "medium", 0);
    av_dict_set(&param, "tune", "zerolatency", 0);
    

    //Encoder
    encoder = avcodec_find_encoder(codec_id);
    if(!encoder){
        std::cout << "Encoder avcodec_find_encoder error!" << std::endl;
        return -1;
    }

    encoder_context = avcodec_alloc_context3(encoder);
    if(!encoder_context){
        std::cout << "Encoder avcodec_alloc_context3 error!" << std::endl;
        return  -1;
    }
    
    int frame_rate = 30;
    {
        encoder_context->bit_rate = 400000;
        encoder_context->width = image_width;
        encoder_context->height = image_height;
        encoder_context->framerate = AVRational({1, frame_rate});

        encoder_context->time_base.num = 1;
        encoder_context->time_base.den = 25;
        encoder_context->max_b_frames = 0; // no bframes
        encoder_context->codec_type = codec_type;
        encoder_context->pix_fmt = pix_fmt;
    }           

    ret = avcodec_open2(encoder_context, encoder, &param);
    if(ret < 0){
        std::cout << "Encoder avcodec_open2 error!" << std::endl;
        return  -1;
    }
    std::cout << "-------- VideoEncoder: --------" << "\n"
        << "\ncamera:  " << image_width << 'x' << image_height << '@' << frame_rate << "\n"
        << "vcodec:  " << encoder->name << "\n"
        << "size:    " << image_width << 'x' << image_height << "\n"
        << "fps:     " << av_q2d(encoder_context->framerate) << "\n"
        << "pixfmt:  " << av_get_pix_fmt_name(encoder_context->pix_fmt) << std::endl;
    std::cout << "Initialize Video Encoder finished!" << std::endl;

    //Decoder
    decoder = avcodec_find_decoder(codec_id);
    if(!decoder){
        std::cout << "avcodec_find_decoder error!" << std::endl;
        return -1;
    }
    
    decoder_context = avcodec_alloc_context3(decoder);
    if(!decoder_context){
        std::cout << "Decoder avcodec_alloc_context3 error!" << std::endl;
        return -1;
    }
    
    ret = avcodec_open2(decoder_context, decoder, NULL);
    if(ret < 0){
        std::cout << "Decoder avcodec_open2 error!" << std::endl;
        return  -1;
    }
    
    parser = av_parser_init(decoder->id);
    if(!parser){
        std::cout << "Decoder av_parser_init error!" << std::endl;
        return -1;
    }
    
    std::cout << "Initialize Video Decoder finished!" << std::endl;

    encoder_sws_context = sws_getContext(
        image_width, image_height, sws_pix_fmt,
        image_width, image_height, pix_fmt,
        SWS_BILINEAR, NULL, NULL, NULL
    );
    
    decoder_sws_context = sws_getContext(
        image_width, image_height, pix_fmt,
        image_width, image_height, sws_pix_fmt,
        SWS_BILINEAR, NULL, NULL, NULL
    );

    if(!encoder_sws_context || !decoder_sws_context){
        std::cout << "sws_getContext error!" << std::endl;
        return  -1;
    }
    
    return 0;
}   

int VideoCodec::encode(Datatype &_raw_data, Binary_Data *_encode_data){
    
    // std::cout << "Videocodec encode" << std::endl;
    if (std::holds_alternative<cv::Mat>(_raw_data)){
        
        const cv::Mat &image = std::get<cv::Mat>(_raw_data);
        //std::cout << "convert success " << std::endl;
        int ret;
        AVFrame *av_frame;
        AVPacket *av_packet;
        
        av_frame = av_frame_alloc();
        av_packet = av_packet_alloc();

        av_frame->format = encoder_context->pix_fmt;
        av_frame->width = encoder_context->width;
        av_frame->height = encoder_context->height;

        ret = av_image_alloc(
            av_frame->data, av_frame->linesize, 
            encoder_context->width, 
            encoder_context->height, 
            encoder_context->pix_fmt, 
            32
        );

        if(ret < 0){
            std::cout << "encode av_image_alloc_error" << std::endl;
            return  -1;
        }

        av_frame->pts = 1;
        const int stride[4] = {static_cast<int> (image.step[0])};
        
        sws_scale(
            encoder_sws_context, &image.data, stride, 0, image.rows, av_frame->data, av_frame->linesize
        );

        ret = avcodec_send_frame(encoder_context, av_frame);
        if(ret < 0){
            std::cout << "avcodec_send_frame error!" << std::endl;
            av_freep(av_frame->data);
            av_frame_free(&av_frame);
            av_packet_free(&av_packet);
            return -1;
        }

        bool has_data = false;

        while(ret >= 0){
            ret = avcodec_receive_packet(encoder_context, av_packet);
            if (ret < 0){
                if(ret == AVERROR(EAGAIN)){
                    //std::cout << "---- EAGAIN in encode ----" << std::endl;
                }else if(ret == AVERROR_EOF){
                    //std::cout << "---- EOF in encode ----" << std::endl;
                }
            }
            
            if(av_packet->size > 0){
                _encode_data->buffer = (uint8_t *)realloc(_encode_data->buffer, sizeof(uint8_t)* (_encode_data->size + av_packet->size));
                if (_encode_data->buffer == NULL){
                    std::cout << "Error in realloc buffer size in encode!" << std::endl;
                    exit(-1);
                }
                has_data = true;
                std::memcpy((_encode_data->buffer) + (_encode_data->size), av_packet->data, av_packet->size);
                (_encode_data->size) += av_packet->size;
            }
            
        }

        av_freep(av_frame->data);
        av_frame_free(&av_frame);
        av_packet_free(&av_packet);

        return has_data ? 0 : -1;    
    }

    std::cout << "Invalid input data type, the type should be cv::Mat" << std::endl;
    return -1;
}

int VideoCodec::decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data){

    AVFrame *av_frame;
    AVPacket *av_packet;
    
    av_frame = av_frame_alloc();
    av_packet = av_packet_alloc();

    uint8_t *pos;
    int ret_size;
    int ret;
    
    pos = _encode_data->buffer;
    ret_size = _encode_data->size;
    
    bool has_decode_images = false;

    while(ret_size > 0){
        ret = av_parser_parse2(
            parser, decoder_context, &av_packet->data, &av_packet->size, 
            pos, ret_size, AV_NOPTS_VALUE, AV_NOPTS_VALUE, 0
        );

        if (ret < 0){
            std::cout << "av_parser_parse2 error!" << std::endl;
            return -1;
        }

        pos += ret;
        ret_size -= ret;

        if(av_packet->size){
            ret = avcodec_send_packet(decoder_context, av_packet);
            if (ret < 0){
                std::cout << "---- avcodec_send_packet error! ----" << std::endl;
                av_frame_free(&av_frame);
                av_packet_free(&av_packet);
                return -1;
            }

            while(
                (ret = avcodec_receive_frame(decoder_context, av_frame)) >= 0
            ){
                int width = av_frame->width;
                int height = av_frame->height;

                cv::Mat decode_image(height, width, CV_8UC3);

                int cvLinesizes[1];

                cvLinesizes[0] = decode_image.step1();

                sws_scale(
                    decoder_sws_context, av_frame->data, av_frame->linesize, 0, height, &(decode_image.data), cvLinesizes
                );

                //std::cout << "------ Got decode frame ------" << std::endl;
                _decode_data.push_back(std::move(decode_image));
                has_decode_images = true;
            }
        }
    }

    av_frame_free(&av_frame);
    av_packet_free(&av_packet);
    return has_decode_images ? 0 : -1;
    
}