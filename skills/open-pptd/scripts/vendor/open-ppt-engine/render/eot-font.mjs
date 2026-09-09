/** PowerPoint uses EOT font parts (MS-OE376 §15.2.12), not Word's obfuscation.
 * Uncompressed EOT v2.1: https://www.w3.org/submissions/EOT/#Version00020001
 * The original SFNT bytes and embedding permission bits are preserved.
 */
export function encodeEotFont(input) {
  const bytes = Buffer.from(input);
  if (bytes.length < 12 || ![0x00010000, 0x4f54544f].includes(bytes.readUInt32BE(0))) {
    throw new Error('EOT requires a standalone TrueType or OpenType font');
  }
  const tables = new Map();
  const count = bytes.readUInt16BE(4);
  for (let i = 0; i < count; i++) {
    const offset = 12 + i * 16;
    if (offset + 16 > bytes.length) throw new Error('Truncated SFNT table directory');
    const start = bytes.readUInt32BE(offset + 8), size = bytes.readUInt32BE(offset + 12);
    if (start + size > bytes.length) throw new Error('Truncated SFNT table');
    tables.set(bytes.toString('ascii', offset, offset + 4), bytes.subarray(start, start + size));
  }
  const os2 = tables.get('OS/2'), head = tables.get('head'), names = tables.get('name');
  if (!os2 || os2.length < 64 || !head || head.length < 12 || !names || names.length < 6) {
    throw new Error('Font lacks the metadata required for EOT');
  }
  const header = Buffer.alloc(80);
  header.writeUInt32LE(bytes.length, 4);
  header.writeUInt32LE(0x00020001, 8);
  os2.copy(header, 16, 32, 42);
  header[26] = 1;
  header[27] = os2.readUInt16BE(62) & 1;
  header.writeUInt32LE(os2.readUInt16BE(4), 28);
  header.writeUInt16LE(os2.readUInt16BE(8), 32);
  header.writeUInt16LE(0x504c, 34);
  for (let i = 0; i < 4; i++) header.writeUInt32LE(os2.readUInt32BE(42 + 4 * i), 36 + 4 * i);
  if (os2.length >= 86 && os2.readUInt16BE(0) >= 1) {
    header.writeUInt32LE(os2.readUInt32BE(78), 52);
    header.writeUInt32LE(os2.readUInt32BE(82), 56);
  }
  header.writeUInt32LE(head.readUInt32BE(8), 60);
  const nameString = (id) => {
    const records = [];
    for (let i = 0; i < names.readUInt16BE(2); i++) {
      const pos = 6 + i * 12;
      if (pos + 12 > names.length) throw new Error('Truncated font names');
      const platform = names.readUInt16BE(pos), language = names.readUInt16BE(pos + 4);
      if (names.readUInt16BE(pos + 6) !== id || ![0, 3].includes(platform)) continue;
      const start = names.readUInt16BE(4) + names.readUInt16BE(pos + 10), size = names.readUInt16BE(pos + 8);
      if (start + size > names.length || size % 2) throw new Error('Invalid font name');
      records.push({ language, text: Buffer.from(names.subarray(start, start + size)).swap16() });
    }
    return (records.find(r => r.language === 0x409) ?? records[0])?.text ?? Buffer.alloc(0);
  };
  const parts = [header];
  for (const id of [1, 2, 5, 4]) {
    const name = nameString(id), prefix = Buffer.alloc(4);
    prefix.writeUInt16LE(name.length, 2);
    parts.push(prefix, name);
  }
  parts.push(Buffer.alloc(4), bytes); // Padding5 and empty RootString.
  const eot = Buffer.concat(parts);
  eot.writeUInt32LE(eot.length, 0);
  return eot;
}
