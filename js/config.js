/* All rules live here. Edit this file to change GCP & Ring, ranges or VLANs. (TEST VALUES ONLY) */
var CFG = {
  gcps: { 'HDGCP1-R1': [18, 1], 'SHGCP1-R1': [19, 1], 'HWGCP1-R1': [20, 1], 'UTGCP1-R1': [21, 1] }, // [octet1 = GCP, octet2 = Ring]
  vlan: { 'HDGCP1-R1': ['1800', '1801'], 'SHGCP1-R1': ['1810', '1811'], 'HWGCP1-R1': ['1820', '1821'], 'UTGCP1-R1': ['1830', '1831'] }, // [RTU VLAN, PLC VLAN]
  vendors: ['Yokogawa', 'Honeywell'],
  max: { Yokogawa: 39, Honeywell: 62 },   // host numbers per GCP & Ring + vendor
  warnAt: 0.9,                            // warn when a range is 90% used
  facilities: ['UTMN', 'HRDH', 'HWYH', 'SDGM'],
  mask: '255.255.255.0'
};
