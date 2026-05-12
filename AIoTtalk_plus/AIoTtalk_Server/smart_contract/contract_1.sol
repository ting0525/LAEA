//SPDX-License-Identifier: MIT
pragma solidity ^0.6.0;

contract SIPtalk_Log{
    
    struct BCProxy_Log{
        string public_key_x_value;
        string public_key_y_value;
        string time;
    }
    
    struct Device_Message{
        string message_id;
        string device_id;
        string data;
        string time;
    }
    
    mapping (string => Device_Message) public device_message_log;
    mapping (string => BCProxy_Log) public bcproxy_log;

    function save_bcproxy_register_log(
        string memory name,
        string memory public_key_x_value,
        string memory public_key_y_value,
        string memory time
    ) public{
        bcproxy_log[name] = BCProxy_Log(
            public_key_x_value,
            public_key_y_value,
            time
        );
    }

    function get_bcproxy_register_log(string memory name) public returns(
        string memory public_key_x_value,
        string memory public_key_y_value,
        string memory time
    ){
        return(
            bcproxy_log[name].public_key_x_value,
            bcproxy_log[name].public_key_y_value,
            bcproxy_log[name].time
        );
    }

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