<?php
function act($pageName) {
    global $active; // good job this is a hacky project
    
    if ($active === $pageName) {
        echo ' class="active"';
    }
}
?>
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" type="text/css" href="<?php echo Utils::base(); ?>/assets/css/bootstrap.min.css" />
<link rel="stylesheet" type="text/css" href="<?php echo Utils::base(); ?>/assets/css/bootstrap-theme.min.css" />
<link rel="stylesheet" type="text/css" href="<?php echo Utils::base(); ?>/assets/css/main.css" />
<title><?php echo (isset($title) ? $title . ' | ' : '') ?>Leeds Hackspace</title>
<script type="text/javascript" src="<?php echo Utils::base(); ?>/assets/js/jquery-2.1.4.min.js"></script>
<script type="text/javascript" src="<?php echo Utils::base(); ?>/assets/js/bootstrap.min.js"></script>
</head>
<body>
<nav class="navbar navbar-inverse navbar-fixed-top">
    <div class="container">
        <div class="navbar-header">
            <button type="button" class="navbar-toggle collapsed" data-toggle="collapse" data-target="#navbar" aria-expanded="false" aria-controls="navbar">
                <span class="sr-only">Toggle navigation</span>
                <span class="icon-bar"></span>
                <span class="icon-bar"></span>
                <span class="icon-bar"></span>
            </button>
            <a href="<?php echo Utils::base(); ?>/" class="navbar-brand">Hackspace DB</a>
        </div>
        <div id="navbar" class="collapse navbar-collapse">
            <ul class="nav navbar-nav">
                <li<?php act('home'); ?>><a href="<?php echo Utils::base(); ?>/">Home</a></li>
                <li<?php act('members'); ?>><a href="<?php echo Utils::base(); ?>/?action=members">Members</a></li>
                <li<?php act('addmember'); ?>><a href="<?php echo Utils::base(); ?>/?action=addmember">Add Member</a></li>
            </ul>
        </div>
    </div>
</nav>
<div class="container">