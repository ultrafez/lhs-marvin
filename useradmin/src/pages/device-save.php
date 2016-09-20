<?php
require_once('utils.php');


if (!(isset($_POST['mac']) && Utils::validateMACAddress($_POST['mac']))) {
    echo 'Invalid MAC address';
    exit;
}

if (!(isset($_POST['description']) && strlen($_POST['description']) <= 256 && strlen($_POST['description']) > 0)) {
    echo 'Invalid description';
    exit;
}

// Caveat: doesn't actually check the owner exists
if (!(isset($_POST['owner']) && preg_match('/\\d+/', $_POST['owner']))) {
    echo 'Invalid owner';
    exit;
}


$system = array();
$system[':mac'] = $_POST['mac'];
$system[':description'] = $_POST['description'];
$system[':source'] = 'e';
$system[':hidden'] = 0;
$system[':owner'] = $_POST['owner'];

try {
    $dbh = Utils::getPdo();

    // Ensure the MAC isn't already in the table
    $macCheckStmt = $dbh->prepare('SELECT COUNT(*) as c FROM systems WHERE mac = :mac');
    $macCheckStmt->execute(['mac' => $_POST['mac']]);
    $foundMacs = $macCheckStmt->fetch();
    if (intval($foundMacs['c']) > 0) {
        throw new Exception('MAC address already in database');
    }

    $systemsStmt = $dbh->prepare('INSERT INTO systems (mac, description, source, hidden, owner) VALUES (:mac, :description, :source, :hidden, :owner)');
    $result = $systemsStmt->execute($system);

    if (!$result) {
        throw new Exception('Couldn\'t insert new system record');
    }

    header('Location: ' . Utils::base() . '/?action=viewmember&id=' . $_POST['owner'] . '&success=1');
    exit;
} catch (Exception $e) {
    require_once('header.php');
?>
    <div class="alert alert-danger">
        <p>Something went wrong: <?php echo $e->getMessage(); ?></p>
    </div>
    <p><a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo $_POST['owner']; ?>">Back to user</a></p>
<?php
    require_once('footer.php');
}
