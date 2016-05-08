<?php
$title = 'Members';
$active = 'members';
require_once('header.php');

$dbh = Utils::getPdo();
?>
<h1>Members</h1>
<table class="table table-striped table-hover table-condensed">
    <thead>
        <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Full Name</th>
            <th>Email</th>
            <th>Member?</th>
            <th>Keyholder?</th>
            <th>Door access</th>
            <th>Payment ref</th>
        </tr>
    </thead>
    <tbody>

<?php foreach ($dbh->query('SELECT * from people;') as $row): ?>
        <tr>
            <td><a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo $row['id']; ?>"><?php echo htmlspecialchars($row['id']); ?></a></td>
            <td><a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo $row['id']; ?>"><?php echo htmlspecialchars($row['name']); ?></a></td>
            <td><a href="<?php echo Utils::base(); ?>/?action=viewmember&id=<?php echo $row['id']; ?>"><?php echo htmlspecialchars($row['fullname']); ?></a></td>
            <td><?php echo htmlspecialchars($row['email']); ?></td>
            <td><?php echo htmlspecialchars($row['member']); ?></td>
            <td><?php echo htmlspecialchars($row['keyholder']); ?></td>
            <td><?php echo htmlspecialchars($row['access']); ?></td>
            <td><?php echo htmlspecialchars($row['paymentref']); ?></td>
        </tr>
<?php endforeach; ?>
    </tbody>
</table>
<?php require_once('footer.php'); ?>