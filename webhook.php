<?php
// Bridge script for cPanel public_html -> FastAPI Uvicorn on http://127.0.0.1:8000/webhook
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

$rawBody = file_get_contents('php://input');
if (empty($rawBody) && !empty($_POST)) {
    $rawBody = json_encode($_POST);
}

$ch = curl_init('http://127.0.0.1:8000/webhook');
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'POST');
curl_setopt($ch, CURLOPT_POSTFIELDS, $rawBody ?: '{}');
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    'Content-Type: application/json',
    'Content-Length: ' . strlen($rawBody ?: '{}')
]);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
curl_setopt($ch, CURLOPT_TIMEOUT, 25);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlErr = curl_error($ch);
curl_close($ch);

if ($response === false) {
    http_response_code(502);
    echo json_encode([
        'status' => 'error',
        'reply' => '',
        'res' => '',
        'error' => 'FastAPI server on 127.0.0.1:8000 is not reachable: ' . $curlErr
    ]);
    exit;
}

http_response_code($httpCode ?: 200);
echo $response;
