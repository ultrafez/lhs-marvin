The space is currently <?php 
# Master source for this widget is stored inthe lhs-marvin repository on github
$state = json_decode(file_get_contents("http://www.leedshackspace.org.uk/status.php"), true);
if ($state['state']['open']) {
  $color="green";
} else {
  $color="red";
}
$msg=$state['state']['message'];
print "<font color=$color>$msg</font>";
 ?>.
