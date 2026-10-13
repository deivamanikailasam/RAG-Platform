# VPN troubleshooting

## Error E-4021

E-4021 means your device certificate has expired. Open Self Service, run "Reinstall VPN profile", then
restart the VPN client.

## Error E-1107

E-1107 means the MFA push timed out. Approve the Okta Verify push within 60 seconds of connecting; if
it keeps failing, check your phone's date and time settings.

## Error E-3003

E-3003 means split tunnelling was blocked by policy. Disconnect from public Wi-Fi networks that use a
captive portal, connect once, then try the VPN again.
