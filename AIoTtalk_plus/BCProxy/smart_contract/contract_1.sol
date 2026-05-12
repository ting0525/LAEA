//SPDX-License-Identifier: MIT
pragma solidity ^0.6.0;

contract SUA_Device_Log{
    
    struct Device_Profile{
        string device_id;
        //address device_virtual_id;
        string secret_key_hash;
    }

    struct Device_Message_Log{
        string device_id;
        string message;
        string time;
    }
    
    mapping (string => Device_Profile) public device_profiles;
    Device_Message_Log [] device_message_logs;
    
    //mapping (string => Device_Message) public device_message_logs;
    
    function save_device_profile(
        string memory device_virtual_id,
        string memory device_id,
        string memory secret_key_hash, 
    ) public{
        device_profiles[device_virtual_id] = Device_Profile(
                device_id,
                secret_key_hash, 
            );
    }


    function get_device_profile(string memory device_virtual_id) public returns( 
        string memory device_id, 
        string memory secret_key_hash, 
    ){
        return (
            device_profiles[device_virtual_id].secret_key_hash,
            device_profiles[device_virtual_id].device_id
        );
    }

    function save_device_message_log(
        string memory device_virtual_id,
        string memory device_id,
        string memory message,
        string memory time
    ) public{
        device_message_log[device_virtual_id] = Device_Message(
            device_id,
            message,
            time
        );
    }

    function get_device_message_log(string memory device_virtual_id) public returns(  
        string memory device_id, 
        string memory message,
        string memory time
    ){
        return (
            device_message_log[device_virtual_id].device_id,
            device_message_log[device_virtual_id].message,
            device_message_log[device_virtual_id].time
        );
    }
    
}