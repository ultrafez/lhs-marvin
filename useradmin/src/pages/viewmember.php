<?php
$title = 'View Member';
$active = 'members';
require_once('header.php');

$dbh = Utils::getPdo();

$personStmt = $dbh->prepare('SELECT * FROM people WHERE id=:id');
$personStmt->execute(array('id' => $_GET['id']));
$person = $personStmt->fetchAll();

if (count($person) > 1) {
    echo 'Multiple user records returned; wat?';
    require_once('footer.php');
    exit;
}

if (count($person) === 0) {
    echo 'Member not found';
    require_once('footer.php');
    exit;
}

$person = $person[0];

$cardStmt = $dbh->prepare('SELECT * FROM rfid_tags WHERE user_id=:id'); 
$cardStmt->execute(array('id' => $_GET['id']));
$cards = $cardStmt->fetchAll();

$deviceStmt = $dbh->prepare('SELECT * FROM systems WHERE owner=:id');
$deviceStmt->execute(array('id' => $_GET['id']));
$devices = $deviceStmt->fetchAll();


if (isset($_GET['success']) && $_GET['success'] === '1') {
?>
    <div class="alert alert-success">
        <p>Success!</p>
    </div>
<?php
}
?>


<h1><?php echo htmlspecialchars($person['fullname']); ?></h1>

<dl class="dl-horizontal">
    <dt>ID</dt>
    <dd><?php echo htmlspecialchars($person['id']); ?></dd>
    <dt>Nickname</dt>
    <dd><?php echo htmlspecialchars($person['name']); ?></dd>
    <dt>Full Name</dt>
    <dd><?php echo htmlspecialchars($person['fullname']); ?></dd>
    <dt>Email</dt>
    <dd><?php echo htmlspecialchars($person['email']); ?></dd>
    <dt>Member?</dt>
    <dd><?php echo htmlspecialchars($person['member']); ?></dd>
    <dt>Physical keyholder?</dt>
    <dd><?php echo htmlspecialchars($person['keyholder']); ?></dd>
    <dt>Door access</dt>
    <dd><?php echo htmlspecialchars($person['access']); ?></dd>
    <dt>Payment ref</dt>
    <dd><?php echo htmlspecialchars($person['paymentref']); ?></dd>
</dl>

<h2>24/7 access status</h2>
<?php
switch ($person['access']):
    case 'BOTH': ?>
        <p>24/7 member</p>
        <form action="<?php echo Utils::base(); ?>/?action=keyholder" method="post">
            <input type="hidden" name="id" value="<?php echo htmlspecialchars($person['id']); ?>" />
            <input type="hidden" name="access" value="NO" />
            <button type="submit" class="btn btn-danger">Revoke keyholder status</button>
        </form>
<?php
        break;

    case 'DOWNSTAIRS': ?>
        <p>Downstairs only (probably a Pedaller)</p>
        <form action="<?php echo Utils::base(); ?>/?action=keyholder" method="post">
            <input type="hidden" name="id" value="<?php echo htmlspecialchars($person['id']); ?>" />
            <input type="hidden" name="access" value="BOTH" />
            <?php if ($person['access'] === 'NO'): ?>
                <button type="submit" class="btn btn-warning">Make keyholder</button>
            <?php endif; ?>
        </form>
<?php
        break;

    case 'NO': ?>
        <p>No 24/7 access</p>
        <form action="<?php echo Utils::base(); ?>/?action=keyholder" method="post">
            <input type="hidden" name="id" value="<?php echo htmlspecialchars($person['id']); ?>" />
            <input type="hidden" name="access" value="BOTH" />
            <?php if ($person['access'] === 'NO'): ?>
                <button type="submit" class="btn btn-warning">Make keyholder</button>
            <?php endif; ?>
        </form>
<?php
        break;
endswitch;
?>

<h2>RFID card(s)</h2>
<?php if (!empty($cards)): ?>
    <ul>
    <?php foreach ($cards as $card): ?>
        <li>
            <p><?php echo htmlspecialchars($card['card_id']); ?></p>
            <a href="<?php echo Utils::base(); ?>/?action=changepin&card_id=<?php echo urlencode($card['card_id']); ?>&user_id=<?php echo urlencode($person['id']); ?>" class="btn btn-default">Change PIN</a>
        </li>
    <?php endforeach; ?>
    </ul>
<?php else: ?>
    <p>None registered</p>
<?php endif; ?>

<h2>Devices</h2>
<table class="table table-striped">
    <thead>
        <tr>
            <th>MAC address</th>
            <th>Description</th>
            <th>Source</th>
            <th>Hidden</th>
        </tr>
    </thead>
    <tbody>
<?php foreach ($devices as $device): ?>
        <tr>
            <td><?php echo htmlspecialchars($device['mac']); ?></td>
            <td><?php echo htmlspecialchars($device['description']); ?></td>
            <td><?php echo htmlspecialchars($device['source']); ?></td>
            <td><?php echo htmlspecialchars($device['hidden']); ?></td>
        </tr>
<?php endforeach; ?>
    </tbody>
    <form action="<?php echo Utils::base(); ?>/?action=savedevice" method="post">
        <tfoot>
            <tr>
                <td colspan="4">Add new...</td>
            </tr>
            <tr>
                <td><input type="text" placeholder="AB:CD:AB:CD:AB:CD" name="mac" class="form-control" pattern="^([A-F\d]{2}:){5}[A-F\d]{2}$" required /></td>
                <td colspan="2"><input type="text" placeholder="Dave's Nexus 6p" name="description" class="form-control" required /></td>
                <td>
                    <input type="hidden" name="owner" value="<?php echo $_GET['id']; ?>" />
                    <button type="submit" class="btn btn-success">Add device</button>
                </td>
            </tr>
        </tfoot>
    </form>
</table>


<?php require_once('footer.php');
