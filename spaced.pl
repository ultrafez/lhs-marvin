#!/usr/bin/perl

# The master copy of this script lives at https://github.com/pbrook/lhs-marvin

use Device::SerialPort;
use DBI;
use IO::Socket;
use Config::Simple;

$channels="#leeds-hack-space,#leedshackspace";

sub ircsend 
{
my $sock = new IO::Socket::INET ( 
      PeerAddr => '10.113.0.1',
      PeerPort => '1889',
      Proto => 'tcp',
      );
die "Failed to connect to Marvin: $!\n" unless $sock;
print $sock "#leeds-hack-space,#leedshackspace ".$_[0];
close($sock);
};

my $cfg = new Config::Simple('/etc/marvin.conf') or die Config::Simple->error();

$db = DBI->connect('DBI:mysql:hackspace', $cfg->param('db.user'), $cfg->param('db.password')) || die "Could not connect to database: $DBI::errstr";

my $port = Device::SerialPort->new("/dev/arduino") or die "Couldn't open serial port\n";
$port->databits(8);
$port->baudrate(9600);
$port->parity("none");
$port->stopbits(1);

my $debug=1;
my $string,$pirstate,$lastpirstate,$doorstate,$lastdoorstate,$doors,$lastpirtime,$tempstate,$lasttemptime,$lastmoflashtime,$johnnywasatspace,$lastjohnnytime,$lastcampos,$lastcamtime,$camreset;

$lasttemptime=0;
$lastpirtime=0;
$lastmoflashtime=0;
$lastjohnnytime=0;
$lastcampos=90;
$lastcamtime=0;
$camreset=0;
$johnnywasatspace=1;

$port->write("\r");
$port->write("MO00\r");
$port->write("L\r");
sleep(1);

# Initialise door state
$lastdoorstate=0;
$doorstate=0;
$spacestate=2;

sub getcampos
{
      $sql="select * from prefs where ref='webcam';";
      $query=$db->prepare($sql);
      $query->execute();
      $row=$query->fetchrow_hashref();
      return $row->{'value'};
};

sub processmoflash
{
      $sql="select * from events where command like 'M%' and processed=false limit 1;";
      $query=$db->prepare($sql);
      $query->execute();
      while ($row=$query->fetchrow_hashref())
      {
            print $row->{'id'}." ".$row->{'time'}." ".$row->{'command'}."\n" if ($debug==1);
            $port->write("\r".$row->{'command'}."\r");
            $sql="update events set processed=true where id=".$row->{'id'}.";";
            $db->do($sql);
            $lastmoflashtime=time();
            $lastmoflashtime=time()-10 if ($row->{'command'}=~/^MO/);
      };
};

sub processwebcam
{
      $sql="select * from events where (command like 'W%' or command like 'L%' or command like 'Z%') and processed=false limit 1;";
      $query=$db->prepare($sql);
      $query->execute();
      while ($row=$query->fetchrow_hashref())
      {
            print $row->{'id'}." ".$row->{'time'}." ".$row->{'command'}."\n" if ($debug==1);
            $port->write($row->{'command'}."\r");
            sleep(10) if ($row->{'command'}=~/^Z/);
            $sql="update events set processed=true where id=".$row->{'id'}.";";
            $db->do($sql);
      };
};

sub heresjohnny
{
      $sql="select name from people_list where name = 'Jonny' limit 1";
      $query=$db->prepare($sql);
      $query->execute();
      my $count=0;
      while($row=$query->fetchrow_hashref()){
            $count++;
      };
      if ($count>0){
            $johnnyatspace=1; 
      } else {
            $johnnyatspace=0; 
      };
      if (($johnnywasatspace==0) && ($johnnyatspace==1)){
            system("play /sites/status/docs/heresjohnny.wav");
      };
      $johnnywasatspace=$johnnyatspace;
      $lastjohnnytime=time();
};

sub setsign
{
    $sql="select value from prefs where ref='space-state';";
    $sth = $db->prepare($sql);
    $nrows = $sth->execute();
    @rows = $sth->fetchrow_array;
    if (($rows[0] eq "2") || ($rows[0] eq "4"))
    {
	$port->write("S0\r");
    } else {
	$port->write("S1\r");
    }
}

sub processpir
{
      $port->write("P\r");
      sleep(1);
      $stuff=$port->input;
      print "R:".$stuff if ($debug==1);
      chop $stuff;
      chop $stuff;
      ($junk,$pirstate)=split(/\=/,$stuff);
      if ($pirstate eq "1" && $lastpirstate ne "1")
      {
            print "PIR Triggered\n" if ($debug==1);
            $sql="insert into security values(default,default,'PIR Triggered');";
            $db->do($sql);
            $lastpirstate=$pirstate;
      };
      if ($pirstate eq "0" && $lastpirstate ne "0")
      {
            print "PIR Reset\n" if ($debug==1);
            $sql="insert into security values(default,default,'PIR Reset');";
            $db->do($sql);
            $lastpirstate=$pirstate;
      };

      $port->write("D\r");
      sleep(1);
      $stuff=$port->input;
      print "R:".$stuff if ($debug==1);
      chop $stuff;
      chop $stuff;
      ($junk,$doors)=split(/\=/,$stuff);
      ($doorstate,$junk)=split(/,/,$doors);
      if ($doorstate eq "1" && $lastdoorstate ne "1")
      {
            print "Door Opened\n" if ($debug==1);
            $sql="insert into security values(default,default,'Door Opened');";
            $db->do($sql);
            $sql="replace into prefs values('internaldoor','open');";
            $db->do($sql);
            $sql="insert into events values (default,default,'door','W180',default);";
            $db->do($sql);
            $lastcampos=getcampos();
            $lastcamtime=time();
            $camreset=1;
            print "Camera position recorded at ".$lastcampos."\n";
           
	    $sql="select value from prefs where ref='space-state';";
	    $sth = $db->prepare($sql);
	    $nrows = $sth->execute();
	    @rows = $sth->fetchrow_array;
            if (($rows[0] eq "2") || ($rows[0] eq "4"))
            {
		ircsend("Internal door opened");
            }
	    $lastdoorstate=$doorstate;
      };
      if ($doorstate eq "0" && $lastdoorstate ne "0")
      {
            print "Door Closed\n" if ($debug==1);
            $sql="insert into security values(default,default,'Door Closed');";
            $db->do($sql);
            $sql="replace into prefs values('internaldoor','closed');";
            $db->do($sql);

	     $sql="select value from prefs where ref='space-state';";
	     $sth = $db->prepare($sql);
	     $nrows = $sth->execute();
	     @rows = $sth->fetchrow_array;
	     if (($rows[0] eq "2") || ($rows[0] eq "4"))
	     {           
 
	    	ircsend("Internal door closed");
            }
	    $lastdoorstate=$doorstate;
      };
      setsign()
};

sub processtemp
{
      print "Temperature\n" if ($debug==1);
      $lasttemptime=time();
      $port->write("T\r");
      sleep(1);
      $stuff=$port->input;
      print "R:".$stuff if ($debug==1);
      chop $stuff;
      chop $stuff;
      ($junk,$tempstate)=split(/\=/,$stuff);
      print "Current temperature is: ".$tempstate."°C\n" if ($debug==1);
      # db connect to catch any dropped connections
      $db = DBI->connect('DBI:mysql:hackspace', 'hackspace', 'hackspace') || die "Could not connect to database: $DBI::errstr";
      if ($tempstate != ''){
            $sql="insert into environmental values(default,".$tempstate.");";
            print $sql."\n";
            $db->do($sql);
      };
#      $mqtt="mosquitto_pub -h api.cosm.com -u BOLflayEi_L-EOA2KZH8GkjxlPCSAKx4TE14cERzdTBYdz0g -t /v2/feeds/73250/datastreams/1.csv -m ".$tempstate;
#      print $mqtt."\n";
#      system($mqtt);
};

while(1) {
      ####################################################
      ## Process webcam pan and laser events immediately
      ####################################################
      processwebcam();
      ###########################################
      ## Process moflash events every 10 seconds
      ###########################################
      processmoflash() if (time()>=$lastmoflashtime+10);
      ##############################
      ## Check for Johnny every 15s
      ##############################
      #heresjohnny() if (time()>=$lastjohnnytime+15);
      ######################################
      ## Check PIR and door every 2 seconds
      ######################################
      processpir() if (time()>=$lastpirtime+2);
      ################################
      ## Check temp every 60 seconds
      ################################
      processtemp() if (time()>=$lasttemptime+60);
      
      if (time()>$lastcamtime+10&&$camreset==1)
      {
            print "Resetting camera position\n";
            $camreset=0;
            $sql="insert into events values (default,default,'door','W".$lastcampos."',default);";
            $db->do($sql);
      };
}
