<?php
$title = 'Add Member';
$active = 'addmember';
require_once('header.php');

// Validate we submitted everything

if (!isset($_POST['name']) || !isset($_POST['fullname']) || !isset($_POST['email']) || !isset($_POST['paymentref']) || !isset($_POST['card_id']) || !isset($_POST['pin'])) {
    echo 'You missed out a required field; exiting';
    exit;
}

if (strlen($_POST['name']) > 255 || strlen($_POST['fullname']) > 65535 || strlen($_POST['email']) > 255 || strlen($_POST['paymentref']) > 10 || strlen($_POST['card_id']) > 14) {
    echo 'One or more fields were too long';
    exit;
}

if ($_POST['pin'] !== '' && !Utils::validatePin($_POST['pin'])) {
    echo 'PIN is invalid. It must be between 4 and 14 digits, with no two consecutive digits the same';
    exit;
}


$makeKeyholder = $_POST['pin'] !== '';

$user = array();
$user[':name'] = $_POST['name'];
$user[':fullname'] = $_POST['fullname'];
$user[':email'] = $_POST['email'];
$user[':paymentref'] = $_POST['paymentref'];
$user[':member'] = 'YES';
$user[':keyholder'] = 'NO';
$user[':access'] = $makeKeyholder ? 'BOTH' : 'NO';

$card = array();
$card[':card_id'] = strtoupper($_POST['card_id']);
$card[':pin'] = $makeKeyholder ? $_POST['pin'] : '38169352'; // change this for the member later

$systems = array();
$systems[':mac'] = strtoupper($_POST['card_id']);
$systems[':description'] = 'RFID';
$systems[':source'] = 'r';
$systems[':hidden'] = 0;

try {
    $dbh = Utils::getPdo();

    try {
        $peopleStmt = $dbh->prepare('INSERT INTO people (id, name, fullname, email, member, keyholder, access, paymentref) VALUES (null, :name, :fullname, :email, :member, :keyholder, :access, :paymentref)');
        $result = $peopleStmt->execute($user);

        if (!$result) {
            throw new Exception('Couldn\'t insert new person record');
        }

        $id = $dbh->lastInsertId();

        $card[':user_id'] = $id;

        $cardStmt = $dbh->prepare('INSERT INTO rfid_tags (card_id, pin, user_id) VALUES (:card_id, :pin, :user_id)');
        $result = $cardStmt->execute($card);

        if (!$result) {
            throw new Exception('Couldn\'t insert card record');
        }
?>
    <div class="alert alert-success">Member added. <a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo urlencode($id); ?>">View profile</a></div>
<?php
    } catch (Exception $e) {
?>
    <div class="alert alert-danger">
        <p>Partially failed; unable to rollback due to lack of transactions! If it failed at inserting the card, you have created the user but not the card: <?php echo $e->getMessage(); ?></p>
        <p>If you're lucky, you can probably press Back and your form contents will still be there.</p>
    </div>
<?php
    }
} catch (Exception $e) {
    echo '<div class="alert alert-danger">PDO failed ' . $e->getMessage() . '</div>';
}
?>
<p><a href="<?php echo Utils::base(); ?>/">Main menu</a></p>
<?php require_once('footer.php'); ?>
