<?php
require_once('config.php');
require_once('utils.php');

if (!isset($_GET['action'])) {
    require_once('pages/main.php');
    exit;
}

// super dumb router
$action = $_GET['action'];
$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET' && $action === 'addmember') {
    require_once('pages/addmember-form.php');
} else if ($method === 'POST' && $action === 'addmember') {
    require_once('pages/addmember-save.php');
} else if ($method === 'GET' && $action === 'members') {
    require_once('pages/members.php');
} else if ($method === 'GET' && $action === 'viewmember') {
    if (isset($_GET['id'])){
        require_once('pages/viewmember.php');
    } else {
        echo 'nope';
    }
} else if ($method === 'POST' && $action === 'keyholder') {
    require_once('pages/keyholder.php');
} else if ($method === 'GET' && $action === 'changepin') {
    if (isset($_GET['card_id']) && isset($_GET['user_id'])) {
        require_once('pages/changepin-form.php');
    } else {
        echo 'nope';
    }
} else if ($method === 'POST' && $action === 'changepin') {
    require_once('pages/changepin-save.php');
} else if ($method === 'POST' && $action === 'savedevice') {
    require_once('pages/device-save.php');
} else {
    echo 'Unknown action';
}
