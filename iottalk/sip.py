import DAN,csmapi, random, time, threading, json
import rospy
from std_msgs.msg import String

# Publish the SDP to the ROS Topic
sip_sender = rospy.Publisher('sip_sender_sdp', String, queue_size=10, latch=True) # Topic name = sip_sender_sdp
sip_receiver = rospy.Publisher('sip_receiver_sdp', String, queue_size=10, latch=True) # Topic name = sip_receiver_sdp

def IoTtalk_registration():
    # set IoTtalk Server URL
    IoTtalk_ServerURL = 'http://140.114.77.93:9999'
    Reg_addr = None
    
    # set device profile
    DAN.profile['dm_name'] = 'SIP_SDP'
    DAN.profile['df_list'] = ['SIP_Sender', 'SIP_Receiver']
    
    # register device profile to IoTtalk Server
    DAN.device_registration_with_retry(IoTtalk_ServerURL, Reg_addr)
    print("Register successfully")  

def RTPSender(IDF, ODF):
    # Register the IotTalk Server
    flag = False

    # Start the RTP Sender
    # 1. Push the SDP to the IoTtalk Server (Invite)
    flag = False
    while not flag:
        try:
            # depth-only SDP
            sip = 'a=1 12000 depth_stream video 97 sendonly\n'
            # full SDP
            # sip = 'a=0 10000 rgb_stream video 96 sendonly\n' + \
            #       'a=1 12000 depth_stream video 97 sendonly\n' + \
            #       'a=2 14000 point_cloud pointcloud 98 sendonly\n' + \
            #       'a=3 16000 scan_point_cloud pointcloud 99 sendonly\n' + \
            #       'a=4 18000 camera_info camera_info 100 sendonly\n' + \
            #       'a=5 20000 map_point_cloud pointcloud 101 sendonly\n' + \
            #       'a=6 22000 position_visualization marker 102 sendonly\n' + \
            #       'a=7 24000 position_command command 103 sendonly\n' + \
            #       'a=8 26000 local_odom odom 104 sendonly\n' + \
            #       'a=9 28000 pose pose 105 sendonly\n'
            
            
            packet = {'type': 'Invite', 'source': 'CD8600D38000', 'target': 'CD8600D38001', 'sdp_data': sip}
            result = DAN.push(IDF, json.dumps(packet))
            if result != None:
                print(f'RTP Sender: Success to Invite')
                flag = True
            else:
                print('Failed to Invite. Retrying...')
                # Wait for 1 second
                time.sleep(5)
        except Exception as e:
            print(f'RTP Sender Invite error: {e}')
            time.sleep(1)
    
    # 2. Wait for the SDP from the IoTtalk Server (OK)
    flag = False
    while not flag:
        try:
            result = DAN.pull(ODF)
            if result != None:
                packet = json.loads(result[0])
                if packet['type'] == 'OK':
                    flag = True

                    # Publish the SDP to the ROS Topic
                    sip_sender.publish(packet['sdp_data'])

                print(f'RTP Sender: {packet}')
            else:
                # Wait for 1 second
                print('Waiting for the SDP from Receiver...')
                time.sleep(5)
        except Exception as e:
            print(f'RTP Sender pull OK error: {e}')
            time.sleep(1)

def RTPReceiver(IDF, ODF):
    # Register the IotTalk Server

    # Start the RTP Receiver
    # 1. Wait for the SDP from the IoTtalk Server (Invite)
    flag = False
    while not flag:
        try:
            result = DAN.pull(IDF)
            if result != None:
                packet = json.loads(result[0])
                if packet['type'] == 'Invite':
                    flag = True

                    # Publish the SDP to the ROS Topic
                    sip_receiver.publish(packet['sdp_data'])

                print(f'RTP Receiver: {packet}')
            else:
                # Wait for 1 second
                print('Waiting for the SDP from the Sender...')
                time.sleep(5)
        except Exception as e:
            print(f'RTP Receiver pull Invite error: {e}')
            time.sleep(1)  

    # 2. Push the SDP to the IoTtalk Server (OK)
    flag = False
    while not flag:
        try:
            
            # depth-only SDP
            sip = 'a=1 13000 depth_stream video 97 recvonly\n'
            
            # full SDP
            # sip = 'a=0 11000 rgb_stream video 96 recvonly\n' + \
            #       'a=1 13000 depth_stream video 97 recvonly\n' + \
            #       'a=2 15000 point_cloud pointcloud 98 recvonly\n' + \
            #       'a=3 17000 scan_point_cloud pointcloud 99 recvonly\n' + \
            #       'a=4 19000 camera_info camera_info 100 recvonly\n' + \
            #       'a=5 21000 map_point_cloud pointcloud 101 recvonly\n' + \
            #       'a=6 23000 position_visualization marker 102 recvonly\n' + \
            #       'a=7 25000 position_command command 103 recvonly\n' + \
            #       'a=8 27000 local_odom odom 104 recvonly\n' + \
            #       'a=9 29000 pose pose 105 recvonly\n'
            packet = {'type': 'OK', 'source': 'CD8600D38001', 'target': 'CD8600D38000', 'sdp_data': sip}
            result = DAN.push(ODF, json.dumps(packet))
            if result != None:
                print(f'RTP Receiver: Success to OK')
                flag = True
            else:
                print('Failed to OK. Retrying...')
                # Wait for 1 second
                time.sleep(5)
        except Exception as e:
            print(f'RTP Receiver push OK error: {e}')
            time.sleep(1)

def SIP_Dialog():
    # 1. Register the IotTalk Server
    IoTtalk_registration()

    # Auto start without user input
    print('Start the SIP Dialog...')
    # 2. Start the SIP Dialog by creating the SIP Sender and Receiver
    sender = threading.Thread(target=RTPSender, args=('SIP_Sender', 'SIP_Receiver'))
    receiver = threading.Thread(target=RTPReceiver, args=('SIP_Sender', 'SIP_Receiver'))

    sender.start()
    receiver.start()

if __name__ == '__main__':
    # ROS node
    rospy.init_node('SIP_SDP')
    SIP_Dialog()
    rospy.spin()
