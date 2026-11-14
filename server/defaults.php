<?php
// Seed rules used on first setup only (DUMMY TEST VALUES). Afterwards the rules live in the database
// and are changed from the Settings page. Never put real company values in this file.
return [
    'facilities' => ['UTMN', 'HRDH', 'HWYH', 'SDGM'],
    // code, octet1, octet2, RTU VLAN, PLC VLAN
    'gcp_rings' => [
        ['HDGCP1-R1', 18, 1, '1800', '1801'],
        ['SHGCP1-R1', 19, 1, '1810', '1811'],
        ['HWGCP1-R1', 20, 1, '1820', '1821'],
        ['UTGCP1-R1', 21, 1, '1830', '1831'],
    ],
    // every address is host = a * n + b on a network slot (A, B or M = Moxa network)
    'vendors' => [
        [
            'name' => 'Yokogawa', 'capacity' => 39, 'octets' => ['A' => 20, 'B' => 21, 'M' => 10],
            'fields' => [
                ['field' => 'RTU IP-1', 'net' => 'A', 'a' => 1, 'b' => 168],
                ['field' => 'RTU IP-2', 'net' => 'B', 'a' => 1, 'b' => 168],
                ['field' => 'PLC IP-1', 'net' => 'A', 'a' => 1, 'b' => 84],
                ['field' => 'PLC IP-2', 'net' => 'B', 'a' => 1, 'b' => 84],
                ['field' => 'RTU Internal IP-1', 'net' => 'A', 'a' => 1, 'b' => 0],
                ['field' => 'RTU Internal IP-2', 'net' => 'B', 'a' => 1, 'b' => 0],
                ['field' => 'RTU-HMI IP', 'net' => 'A', 'a' => 1, 'b' => 210],
                ['field' => 'IES Moxa IP', 'net' => 'M', 'a' => 1, 'b' => 0],
                ['field' => 'Engg. Laptop IP', 'net' => 'A', 'a' => 0, 'b' => 250],
                ['field' => 'Gateway-1', 'net' => 'A', 'a' => 0, 'b' => 253],
                ['field' => 'Gateway-2', 'net' => 'B', 'a' => 0, 'b' => 253],
            ],
        ],
        [
            'name' => 'Honeywell', 'capacity' => 62, 'octets' => ['A' => 100, 'B' => 101, 'M' => 11],
            'fields' => [
                ['field' => 'RTU IP-1', 'net' => 'A', 'a' => 4, 'b' => -3],
                ['field' => 'RTU IP-2', 'net' => 'A', 'a' => 4, 'b' => -2],
                ['field' => 'PLC IP-1', 'net' => 'A', 'a' => 4, 'b' => -1],
                ['field' => 'PLC IP-2', 'net' => 'A', 'a' => 4, 'b' => 0],
                ['field' => 'RTU-HMI IP', 'net' => 'B', 'a' => 1, 'b' => 0],
                ['field' => 'IES Moxa IP', 'net' => 'M', 'a' => 1, 'b' => 0],
                ['field' => 'Engg. Laptop IP', 'net' => 'A', 'a' => 0, 'b' => 250],
                ['field' => 'Gateway-1', 'net' => 'A', 'a' => 0, 'b' => 253],
                ['field' => 'Gateway-2', 'net' => 'B', 'a' => 0, 'b' => 253],
            ],
        ],
    ],
    'settings' => ['warn_at' => '0.9', 'subnet_mask' => '255.255.255.0'],
];
