<html>
<body>
<?php
include 'include/db.php';
$sql="select time, message from security where message like '%door\_%' order by time desc limit 20;";
$r=mysql_query($sql);
while ($row = mysql_fetch_assoc($r)) {
print $row['time'] . ": " . $row['message'] . "<br>\n";
}
?>
</body>
</html>
