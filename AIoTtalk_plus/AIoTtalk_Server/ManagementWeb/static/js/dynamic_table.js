onerror=handleErr
var txt=""

function handleErr(msg,url,l)
{
    txt="本页中存在错误。\n\n"
    txt+="错误：" + msg + "\n"
    txt+="URL: " + url + "\n"
    txt+="行：" + l + "\n\n"
    txt+="点击“确定”继续。\n\n"
    alert(txt)
    return true
}

function addRow(name, color, size, unit, discount, count, sum)
{

    var bodyObj=document.getElementById("goods");

    if(bodyObj==null) 
    {
        alert("Body of Table not Exist!");
        return;
    }

    var rowCount = bodyObj.rows.length;
    //var cellCount = myarray.length;
    var newRow = bodyObj.insertRow(rowCount++);
    newRow.insertCell(0).innerHTML=name;

    newRow.insertCell(1).innerHTML=color;

    newRow.insertCell(2).innerHTML=size;

    newRow.insertCell(3).innerHTML=unit;

    newRow.insertCell(4).innerHTML=discount;

    newRow.insertCell(5).innerHTML=count;

    newRow.insertCell(6).innerHTML=sum;
}

function removeRow(tbodyID, row)
{

    var bodyObj=document.getElementById(tbodyID);

    if(bodyObj==null) 

    {

        alert("Body of Table not Exist!");

        return;

    }
    var nrow = Number(row);
    if (nrow <= bodyObj.rows.length)
        bodyObj.deleteRow(nrow);
    else
        alert("nrow is less.");
}

function modifyRow(tbodyID, row, col, newvalue)
{
    var nrow = Number(row);
    var ncol = Number(col);
    var bodyObj=document.getElementById(tbodyID);

    if(bodyObj==null) 
    {
        alert("Body of Table not Exist!");
        return;
    }
    try
    {
        //var tableObj = bodyObj.parentNode;
        if (nrow < bodyObj.rows.length && ncol < bodyObj.getElementsByTagName('tr')[nrow].getElementsByTagName('td').length)
        {
            //这个在ie下可以 在google下不行
            //bodyObj.rows(nrow).cells(ncol).innerHTML = newvalue;
            //bodyObj.rows[nrow].childNodes[ncol].innerHTML = newvalue;

            //这个在ie和google下都可以
            document.getElementById(tbodyID).getElementsByTagName('tr')[nrow].getElementsByTagName('td')[ncol].innerHTML = newvalue;
        }
        else
            alert("empty.");
    }
    catch (err)
    {
        alert(err.description);
    }

}

function clearRows(tbodyID)
{
    var bodyObj=document.getElementById(tbodyID);
    if(bodyObj==null) 
    {
        alert("Body of Table not Exist!");
        return;
    }

    for (var i = 0; i < bodyObj.rows.length; )
        bodyObj.deleteRow(i);
}