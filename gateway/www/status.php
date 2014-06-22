<?php
include 'include/db.php';

function open_public()
{
  $dow = (int)date("N");
  $hour = (int)date("G");
  if (($dow == 2) && ($hour >= 17)) {
    return True;
  }
  $sql = 'SELECT *' .
	' FROM open_days' .
	' WHERE (start <= now()) AND (end > now())' .
	' LIMIT 1;';
  $r=mysql_query($sql);
  $row = mysql_fetch_assoc($r);
  if ($row) {
    return True;
  } else {
    return False;
  }
}

$state = array(
  'api' => '0.13',
  'space' => 'Leeds Hackspace',
  'logo' => 'http://wiki.leedshackspace.org.uk/leeds_hackspace_logo.png',
  'url' => 'http://www.leedshackspace.org.uk',
  'location' => array(
    'address' => '37-38 Mabgate Green, Leeds, LS9 7DS, England',
    'lat' => 53.800747,
    'lon' => -1.532853,
    ),
  'cam' => array(
    'http://www.leedshackspace.org.uk/cam1.jpg',
    'http://www.leedshackspace.org.uk/cam2.jpg',
    'http://www.leedshackspace.org.uk/cam3.jpg',
    'http://www.leedshackspace.org.uk/cam4.jpg'
    ),
  'state' => array(
    'open' => Null,
    ),
  'contact' => array(
    'twitter' => '@leedshackspace',
    'issue_mail' => 'paul@nowt.org',
    'ml' => 'leeds-hack-space@googlegroups.com',
    'irc' => 'irc://freenode.net/#leeds-hack-space'
    ),
  'issue_report_channels' => array('twitter','issue_mail'),
  'sensors' => array(
    'temperature'         => array(),
    'people_now_present'  => array()
    )
  );

$sql="select * from prefs where ref='space-state';";
$r=mysql_query($sql);
$row = mysql_fetch_assoc($r);
$is_open = (int)$row['value'] == 0;
$state['state']['open'] = $is_open;
if ($is_open) {
  if (open_public()) {
    $msg = 'Open to All';
  } else {
    $msg = 'Open to Members';
  }
} else {
  $msg = 'Closed';
}
$state['state']['message'] = $msg;

$sql="select temperature from temperature limit 1;";
$r=mysql_query($sql);
$row = mysql_fetch_assoc($r);
$temp = array(
  'value' => (int)$row['temperature'],
  'unit' => '°C',
  'location' => 'Inside'
  );
$state['sensors']['temperature'][] = $temp;

$sql="select total from people_count;";
$r=mysql_query($sql);
$row = mysql_fetch_assoc($r);
$peoplecount = $row['total'];
$state['sensors']['people_now_present']['value'] = $peoplecount;

if ($peoplecount > 0) {
  $sql="select name from people_list;";
  $r=mysql_query($sql);
  $people_list = array();
  while ($row = mysql_fetch_assoc($r)) {
    $people_list[] = $row['name'];
  }
  $state['sensors']['people_now_present']['names'] = $people_list;
}

header('Content-type: application/json');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: no-cache');

echo json_encode($state);
