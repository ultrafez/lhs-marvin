<?php
$title = 'Make/Remove Keyholder';
$active = 'members';
require_once('header.php');

if (!isset($_POST['id'])) {
    echo 'You need to submit a user ID';
    require_once('footer.php');
    exit;
}

if (!isset($_POST['access']) || !in_array($_POST['access'], ['BOTH', 'DOWNSTAIRS', 'NO'])) {
    echo 'You need to include a valid door access value';
    require_once('footer.php');
    exit;
}

$dbh = Utils::getPdo();

$personStmt = $dbh->prepare('UPDATE people SET access=:access WHERE id=:id');
$personStmt->execute([
    'id' => $_POST['id'],
    'access' => $_POST['access']
]);

if ($personStmt->rowCount()) {
    echo '<div class="alert alert-success">Success: the member\'s door access is now ' . htmlspecialchars($_POST['access']) . '</div>';
} else {
    echo '<div class="alert alert-danger">Failure: either no member with that ID exists, or they already have the access level you specified</div>';
}

?>

<a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo urlencode($_POST['id']); ?>">Back to profile</a>

<?php require_once('footer.php');