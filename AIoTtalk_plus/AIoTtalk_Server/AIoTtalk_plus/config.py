import os


IoTtalk_info = {
    "IoTtalkServer": "140.114.77.93",
    "IoTtalkServerPort": "9999",
    "ProjectServerPort": os.environ.get("AIOTTALK_PLUS_PROJECT_PORT", "7788"),
    "ProjectName": os.environ.get("AIOTTALK_PLUS_PROJECT_NAME", "AIoTtalk_plus_Auto"),
    "ProjectPassword": os.environ.get("AIOTTALK_PLUS_PROJECT_PASSWORD", ""),
    "SDPParserMac": "SDPParser",
    "SDPParserIDF": "ControlRequest-I",
    "SDPParserODF": "SDPOffer-O",
    "SDPGeneratorMac": "SDPGenerator",
    "SDPGeneratorIDF": "SDPAnswer-I",
    "SDPGeneratorODF": "ControlResponse-O"
}


IoTtalk_project_devices = {
    "sip_signaling": {
        "dm_name": "SIPStream",
        "idf_list": ["SDPOffer-I"],
        "odf_list": ["SDPAnswer-O"],
    },
    "sdp_parser": {
        "dm_name": "SIPStream",
        "idf_list": ["ControlRequest-I"],
        "odf_list": ["SDPOffer-O"],
    },
    "sdp_generator": {
        "dm_name": "SIPStream",
        "idf_list": ["SDPAnswer-I"],
        "odf_list": ["ControlResponse-O"],
    },
    "rtp_device": {
        "dm_name": "SIPStream",
        "idf_list": ["ControlResponse-I"],
        "odf_list": ["ControlRequest-O"],
    },
}


IoTtalk_project_connections = [
    {
        "name": "SIPOfferToParser",
        "from_device": "sip_signaling",
        "from_feature": "SDPOffer-I",
        "to_device": "sdp_parser",
        "to_feature": "SDPOffer-O",
    },
    {
        "name": "ParserToRTPDevice",
        "from_device": "sdp_parser",
        "from_feature": "ControlRequest-I",
        "to_device": "rtp_device",
        "to_feature": "ControlRequest-O",
    },
    {
        "name": "RTPDeviceToGenerator",
        "from_device": "rtp_device",
        "from_feature": "ControlResponse-I",
        "to_device": "sdp_generator",
        "to_feature": "ControlResponse-O",
    },
    {
        "name": "GeneratorToSIPAnswer",
        "from_device": "sdp_generator",
        "from_feature": "SDPAnswer-I",
        "to_device": "sip_signaling",
        "to_feature": "SDPAnswer-O",
    },
]
