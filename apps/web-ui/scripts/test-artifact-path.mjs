import {tmpdir} from 'node:os';
import {join} from 'node:path';

export function testArtifactPath(fileName) {
  return join(tmpdir(), fileName);
}
