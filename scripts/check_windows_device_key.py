import ctypes
import json
import os
from pathlib import Path
import subprocess
from coletor.windows_device_key import NativeCng, WindowsDeviceKey, SOFTWARE_PROVIDER

native = NativeCng()
provider = native.provider(SOFTWARE_PROVIDER)
handle = ctypes.c_size_t()
key = WindowsDeviceKey(crypto=native, provider=SOFTWARE_PROVIDER)
key._provider = provider
try:
    # NULL name creates an ephemeral memory-only key, not the managed/device key.
    native._check(native.dll.NCryptCreatePersistedKey(provider, ctypes.byref(handle), 'ECDSA_P256', None, 0, 0))
    key._key = handle.value
    native.set_dword(handle.value, 'Export Policy', 0)
    native.set_dword(handle.value, 'Key Usage', 2)
    native.finalize(handle.value)
    private_buffer, private_size = ctypes.create_string_buffer(256), ctypes.c_ulong()
    private_status = native.dll.NCryptExportKey(handle.value, 0, 'ECCPRIVATEBLOB', None,
        private_buffer, 256, ctypes.byref(private_size), 0)
    assert private_status != 0, 'Nonexportable policy was not honored'
    challenge = b'isolated-synthetic-device-challenge-2026'
    public = key.public_jwk()
    signature = key.sign_challenge(challenge)
    script = """let s=''; process.stdin.on('data',d=>s+=d); process.stdin.on('end',()=>{
      const crypto=require('node:crypto'); const input=JSON.parse(s);
      const key=crypto.createPublicKey({key:input.public,format:'jwk'});
      const data=Buffer.concat([Buffer.from('Ecossistema.Coletor.DeviceProof.v1\\0'), Buffer.from(input.challenge)]);
      const signature=Buffer.from(input.signature,'base64url');
      const options={key,dsaEncoding:'ieee-p1363'};
      const valid=crypto.verify('sha256',data,options,signature);
      const changed=crypto.verify('sha256',Buffer.concat([data,Buffer.from('changed')]),options,signature);
      console.log(JSON.stringify({valid,changed})); if(!valid||changed)process.exitCode=1;
    });"""
    result = subprocess.run(['node','-e',script], input=json.dumps({'public':public,'signature':signature,'challenge':challenge.decode()}), capture_output=True,text=True,check=True)
    verified = json.loads(result.stdout)
    assert verified == {'valid':True,'changed':False}
    evidence = {'native_cng':'passed','node_webcrypto_compatible_signature':True,'tampered_challenge_rejected':True,
                      'private_export_rejected':True,
                      'private_key_exported':False,'persistent_key_created':False,'device_registered':False,
                      'network_used':False,'provider':'Software KSP; ephemeral NULL-name key'}
    if os.environ.get('QA_OUTPUT'):
        destination = Path(os.environ['QA_OUTPUT'])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'cng.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence))
finally:
    key.close()
