#!/usr/bin/env python3
"""Create a signed local image manifest and immutable Compose image override."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
from environment import read_env
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.secrets/soc-validation.env')
    parser.add_argument('--output',type=Path,default=ROOT/'diagnostics/soc/release')
    args=parser.parse_args();values=read_env(args.env_file);args.output.mkdir(parents=True,exist_ok=True)
    images={}
    for service in ['api','web','runner','postgres','soc','backup']:
        tag=f"{values['VAHAN_IMAGE_NAMESPACE']}/{service}:{values['VAHAN_IMAGE_TAG']}"
        image=json.loads(subprocess.run(['docker','image','inspect',tag],capture_output=True,text=True,check=True).stdout)[0]
        images[service]={'imageId':image['Id'],'tag':tag,'architecture':image['Architecture']}
    paths=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,
                         capture_output=True,check=True).stdout.decode().split('\0')
    hashes={}
    for name in sorted(set(paths)):
        if name.startswith(('apps/','scripts/','docker/','.github/')) or name=='compose.yaml':
            path=ROOT/name
            if path.is_file() and not path.is_symlink() and path.stat().st_size<5*1024*1024:
                hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'createdAt':datetime.now(timezone.utc).isoformat(),'gitHead':subprocess.run(
        ['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),
        'images':images,'sourceHashes':hashes,'localValidationOnly':True}
    encoded=json.dumps(manifest,sort_keys=True,indent=2).encode()+b'\n'
    keyfile=ROOT/'.secrets/release-signing.pem';keyfile.parent.mkdir(exist_ok=True,mode=0o700)
    if keyfile.exists():key=serialization.load_pem_private_key(keyfile.read_bytes(),password=None)
    else:
        key=Ed25519PrivateKey.generate();keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));keyfile.chmod(0o600)
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    (args.output/'manifest.json').write_bytes(encoded)
    (args.output/'manifest.sig').write_bytes(key.sign(encoded))
    (args.output/'public.pem').write_bytes(public)
    key.public_key().verify((args.output/'manifest.sig').read_bytes(),encoded)
    services={name:{'image':images[name]['imageId']} for name in ['api','web','postgres','soc','backup']}
    services.update({'migrate':{'image':images['api']['imageId']},'documents':{'image':images['api']['imageId']}})
    for name in ['runner',*[f'runner-{n}' for n in range(2,11)]]:services[name]={'image':images['runner']['imageId']}
    (args.output/'images.compose.json').write_text(json.dumps({'services':services},indent=2)+'\n')
    print(json.dumps({'manifest':str(args.output/'manifest.json'),'signatureVerified':True,
                      'publicKeyFingerprint':hashlib.sha256(public).hexdigest()}))


if __name__=='__main__':main()
