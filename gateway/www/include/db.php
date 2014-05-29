<?php
$db = mysql_connect("localhost", "hackspace", "hackspace") or die(mysql_error());  
mysql_select_db("hackspace", $db) or die(mysql_error());
?>
