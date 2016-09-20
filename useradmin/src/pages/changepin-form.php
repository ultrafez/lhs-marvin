<?php
$title = 'Change PIN';
$active = 'members';
require_once('header.php');
?>
<h1>Change PIN</h1>
<p>If the member has provisional membership, this function won't be a huge amount of use.</p>
<form action="<?php echo Utils::base(); ?>/?action=changepin" method="POST" class="form-horizontal">
    <input type="hidden" name="card_id" value="<?php echo htmlspecialchars($_GET['card_id']); ?>" />
    <input type="hidden" name="user_id" value="<?php echo htmlspecialchars($_GET['user_id']); ?>" />
    <div class="form-group">
        <label for="pin" class="col-sm-2">New PIN</label>
        <div class="col-sm-10">
            <input type="password" name="pin" id="pin" maxlength="14" class="form-control" pattern="^(?:(?=\d{4,14}$)((\d)(?!\2))+)?$" />
            <p class="help-block">PIN must be: minimum 4 digits, max 14 digits, no duplicate consecutive digits</p>
        </div>
    </div>

    <div class="form-group">
        <div class="col-sm-offset-2 col-sm-10">
            <button type="submit" class="btn btn-primary">Submit</button>
        </div>
    </div>
</form>
<?php require_once('footer.php'); ?>