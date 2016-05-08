<?php
$title = 'Change PIN';
$active = 'members';
require_once('header.php');

// Validate we submitted everything

if (!isset($_POST['pin']) || !isset($_POST['card_id']) || !isset($_POST['user_id'])) {
    echo 'You missed out a required field; exiting';
    require_once('footer.php');
    exit;
}

if (!Utils::validatePin($_POST['pin'])) {
    echo 'PIN is invalid. It must be between 4 and 14 digits, with no two consecutive digits the same';
    require_once('footer.php');
    exit;
}

// SQL time
$dbh = Utils::getPdo();

$stmt = $dbh->prepare('UPDATE rfid_tags SET pin=:pin WHERE card_id=:card_id');
$stmt->execute(array('pin' => $_POST['pin'], 'card_id' => $_POST['card_id']));

if ($stmt->rowCount()) {
    echo '<div class="alert alert-success">PIN changed successfully</div>';
} else {
    echo '<div class="alert alert-danger">Either that card doesn\'t exist, or the PIN is the same as it was before</div>';
}

?>

<a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo urlencode($_POST['user_id']); ?>">Back to profile</a>

<?php require_once('footer.php');