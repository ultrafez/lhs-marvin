<?php
$title = 'Add Member';
$active = 'addmember';
require_once('header.php');
?>
<h1>Add Member</h1>
<div class="alert alert-warning">Ensure the information is correct before submitting, because form fields won't be preserved if there are errors!</div>
<form action="<?php echo Utils::base(); ?>/?action=addmember" method="POST" class="form-horizontal">
    <h2>Personal details</h2>
    <div class="form-group">
        <label for="name" class="col-sm-2">Nickname</label>
        <div class="col-sm-10">
            <input type="text" class="form-control" name="name" id="name" maxlength="65535" required />
            <p class="help-block">Primarily used for IRC and your alias for "who's here"</p>
        </div>
    </div>
    <div class="form-group">
        <label for="fullname" class="col-sm-2">Full name</label>
        <div class="col-sm-10">
            <input type="text" name="fullname" id="fullname" maxlength="255" required class="form-control" />
        </div>
    </div>
    <div class="form-group">
        <label for="email" class="col-sm-2">Email</label>
        <div class="col-sm-10">
            <input type="email" name="email" id="email" maxlength="255" required class="form-control" />
        </div>
    </div>
    <div class="form-group">
        <label for="paymentref" class="col-sm-2">Payment ref</label>
        <div class="col-sm-10">
            <input type="text" name="paymentref" id="paymentref" maxlength="10" required class="form-control" />
            <p class="help-block">Standing order reference</p>
        </div>
    </div>

    <h2>RFID card details</h2>
    <div class="form-group">
        <label for="card_id" class="col-sm-2">Card ID</label>
        <div class="col-sm-10">
            <input type="text" name="card_id" id="card_id" maxlength="14" required class="form-control" />
            <p class="help-block">e.g. A1B2C3D4. List <a href="http://172.31.26.1/doorlog.php" target="_blank">recently scanned cards</a>.</p>
        </div>
    </div>
    <div class="form-group">
        <label for="keyholder" class="col-sm-2">Full member?</label>
        <div class="col-sm-10">
            <input type="checkbox" id="keyholder" />
            <p class="help-block">Full members have 24/7 access; provisional members can use the space when a full member is there.</p>
        </div>
    </div>

    <div class="form-group hidden" id="pin-field">
        <label for="pin" class="col-sm-2">PIN</label>
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

<script type="text/javascript">
$(function () {
    $('#keyholder').on('change', function (e) {
        $('#pin-field').toggleClass('hidden', !this.checked);
    });
});
</script>
<?php require_once('footer.php'); ?>