<?php
require_once('config.php');

class Utils {
    public static function validatePin($pin) {
        // Validate PIN - min 4 digits, max 14 digits, no duplicate digits (a limitation of the Arduino keypad system)
        $pinRegex = '/^(?=\d{4,14}$)' . // ensure PIN is a valid length
                    '(' .
                        '(\d)' . // match a PIN char
                        '(?!\2)' . // ensure the next char isn't the same one
                    ')+$/';

        return preg_match($pinRegex, $pin);
    }

    public static function validateMACAddress($mac) {
        $macRegex = '/([\\dA-F]{2}:){5}[\\dA-F]{2}$/';

        return preg_match($macRegex, $mac);
    }

    public static function getPdo() {
        global $config; // eww
        
        $dsn = 'mysql:dbname=' . $config['mysql_db'] . ';host=' . $config['mysql_host'];
        return new PDO($dsn, $config['mysql_user'], $config['mysql_password'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION
        ]);
    }

    public static function base() {
        global $config;

        return $config['base_path'];
    }
}
