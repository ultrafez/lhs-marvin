<?php
include 'include/db.php';
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
  'sensors' => array()
  );

$sql="select * from prefs where ref='space-state';";
$r=mysql_query($sql);
$row = mysql_fetch_assoc($r);
$ss = $row['value'];
$state['state']['open'] = ($row['value'] == 0);

$sql="select temperature from temperature limit 1;";
$r=mysql_query($sql);
$row = mysql_fetch_assoc($r);
$temp = array(
  'value' => (int)$row['temperature'],
  'unit' => '°C',
  'location' => 'Inside'
  );
$state['sensors']['temperature'] = array($temp);


header('Content-type: application/json');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: no-cache');

echo json_encode($state);
