//SPDX-License-Identifier: MIT
pragma solidity ^0.6.0;

contract AUA_Device_Log{
    

    struct Device_Message{
        string message_id;
        string device_id;
        string data;
        string time;
    }

    mapping (string => Device_Message) public device_message_log;

    function save_device_message_log(
        string memory device_virtual_id,
        string memory message_id,
        string memory device_id,
        string memory data,
        string memory time
    ) public{
        device_message_log[device_virtual_id] = Device_Message(
            message_id,
            device_id,
            data,
            time
        );
    }

    function get_device_message_log(string memory device_virtual_id) public returns(
        string memory message_id,  
        string memory device_id, 
        string memory data,
        string memory time
    ){
        return (
            device_message_log[device_virtual_id].message_id,
            device_message_log[device_virtual_id].device_id,
            device_message_log[device_virtual_id].data,
            device_message_log[device_virtual_id].time
        );
    }
}