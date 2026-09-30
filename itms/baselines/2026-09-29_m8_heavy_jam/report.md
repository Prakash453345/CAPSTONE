
## medium

**seeds 1-5**

| arm | n | mean person-delay (s) | worst run | vs perfect data | vs Webster | vs no count |
|---|---:|---:|---:|---|---|---|
| Webster | 5 | 106,912 | 108,512 | +45.7% **SIG** (0/5 lower) |  |  |
| perfect data | 5 | 73,355 | 74,415 |  | -31.4% **SIG** (5/5 lower) |  |
| camera, no count (before) | 5 | 76,798 | 78,683 | +4.7% **SIG** (0/5 lower) | -28.2% **SIG** (5/5 lower) |  |
| camera, count (adopted) | 5 | 76,798 | 78,683 | +4.7% **SIG** (0/5 lower) | -28.2% **SIG** (5/5 lower) | +0.0% n.s. (0/5 lower) |

| seed | Webster | perfect data | camera, no count (before) | camera, count (adopted) |
|---:|---:|---:|---:|---:|
| 1 | 106,263 | 72,354 | 77,018 | 77,018 |
| 2 | 106,064 | 73,383 | 74,403 | 74,403 |
| 3 | 105,611 | 73,558 | 76,258 | 76,258 |
| 4 | 108,512 | 74,415 | 78,683 | 78,683 |
| 5 | 108,109 | 73,065 | 77,629 | 77,629 |

jam markers (longest wait s / steps to empty the network):

| seed | Webster | perfect data | camera, no count (before) | camera, count (adopted) |
|---:|---:|---:|---:|---:|
| 1 | 603 / 2,364 | 118 / 2,308 | 310 / 2,355 | 310 / 2,355 |
| 2 | 125 / 2,432 | 152 / 2,362 | 102 / 2,370 | 102 / 2,370 |
| 3 | 130 / 2,429 | 123 / 2,388 | 618 / 2,398 | 618 / 2,398 |
| 4 | 133 / 2,428 | 151 / 2,376 | 301 / 2,428 | 301 / 2,428 |
| 5 | 133 / 2,356 | 86 / 2,317 | 127 / 2,309 | 127 / 2,309 |

interlock violations: {'webster': 0, 'truth': 0, 'vision:itms6_640:failsafe:nogap': 0, 'vision:itms6_640:failsafe': 0}; fixed-time fallback ticks: {'webster': 0, 'truth': 0, 'vision:itms6_640:failsafe:nogap': 122, 'vision:itms6_640:failsafe': 122}

## heavy

**seeds 1-10**

| arm | n | mean person-delay (s) | worst run | vs perfect data | vs Webster | vs no count |
|---|---:|---:|---:|---|---|---|
| Webster | 10 | 645,098 | 686,492 | +35.6% **SIG** (0/10 lower) |  |  |
| perfect data | 10 | 475,779 | 546,084 |  | -26.2% **SIG** (10/10 lower) |  |
| camera, no count (before) | 10 | 508,718 | 728,941 | +6.9% n.s. (4/10 lower) | -21.1% **SIG** (9/10 lower) |  |
| camera, count v2 | 10 | 531,192 | 642,017 | +11.6% n.s. (3/10 lower) | -17.7% **SIG** (9/10 lower) | +4.4% n.s. (4/10 lower) |
| camera, count (adopted) | 10 | 504,052 | 593,316 | +5.9% n.s. (3/10 lower) | -21.9% **SIG** (10/10 lower) | -0.9% n.s. (4/10 lower) |

**seeds 1-5**

| arm | n | mean person-delay (s) | worst run | vs perfect data | vs Webster | vs no count |
|---|---:|---:|---:|---|---|---|
| Webster | 5 | 648,447 | 685,933 | +41.8% **SIG** (0/5 lower) |  |  |
| perfect data | 5 | 457,164 | 487,961 |  | -29.5% **SIG** (5/5 lower) |  |
| camera, no count (before) | 5 | 534,887 | 728,941 | +17.0% n.s. (1/5 lower) | -17.5% n.s. (4/5 lower) |  |
| camera, count v2 | 5 | 513,938 | 570,963 | +12.4% **SIG** (1/5 lower) | -20.7% **SIG** (5/5 lower) | -3.9% n.s. (2/5 lower) |
| camera, count (adopted) | 5 | 539,316 | 593,316 | +18.0% n.s. (0/5 lower) | -16.8% **SIG** (5/5 lower) | +0.8% n.s. (1/5 lower) |

**seeds 6-10**

| arm | n | mean person-delay (s) | worst run | vs perfect data | vs Webster | vs no count |
|---|---:|---:|---:|---|---|---|
| Webster | 5 | 641,749 | 686,492 | +29.8% **SIG** (0/5 lower) |  |  |
| perfect data | 5 | 494,393 | 546,084 |  | -23.0% **SIG** (5/5 lower) |  |
| camera, no count (before) | 5 | 482,548 | 557,721 | -2.4% n.s. (3/5 lower) | -24.8% **SIG** (5/5 lower) |  |
| camera, count v2 | 5 | 548,446 | 642,017 | +10.9% n.s. (2/5 lower) | -14.5% n.s. (4/5 lower) | +13.7% n.s. (2/5 lower) |
| camera, count (adopted) | 5 | 468,787 | 516,923 | -5.2% n.s. (3/5 lower) | -27.0% **SIG** (5/5 lower) | -2.9% n.s. (3/5 lower) |

| seed | Webster | perfect data | camera, no count (before) | camera, count v2 | camera, count (adopted) |
|---:|---:|---:|---:|---:|---:|
| 1 | 639,311 | 442,070 | 435,699 | 438,260 | 461,871 |
| 2 | 685,933 | 422,179 | 534,184 | 490,038 | 593,316 |
| 3 | 647,607 | 479,473 | 481,620 | 545,690 | 499,911 |
| 4 | 631,855 | 487,961 | 493,992 | 570,963 | 556,968 |
| 5 | 637,528 | 454,138 | 728,941 | 524,740 | 584,516 |
| 6 | 686,492 | 484,125 | 492,313 | 455,577 | 492,313 |
| 7 | 643,826 | 426,684 | 557,721 | 633,244 | 516,923 |
| 8 | 641,194 | 515,983 | 427,196 | 642,017 | 421,022 |
| 9 | 607,983 | 546,084 | 476,245 | 445,948 | 476,245 |
| 10 | 629,250 | 499,090 | 459,266 | 565,444 | 437,432 |

jam markers (longest wait s / steps to empty the network):

| seed | Webster | perfect data | camera, no count (before) | camera, count v2 | camera, count (adopted) |
|---:|---:|---:|---:|---:|---:|
| 1 | 727 / 2,960 | 419 / 2,486 | 406 / 2,476 | 371 / 2,485 | 546 / 2,682 |
| 2 | 719 / 3,141 | 472 / 2,551 | 641 / 2,537 | 489 / 2,494 | 822 / 2,757 |
| 3 | 716 / 3,137 | 557 / 2,657 | 679 / 2,691 | 674 / 2,721 | 735 / 2,729 |
| 4 | 646 / 3,092 | 481 / 2,532 | 623 / 2,667 | 676 / 2,740 | 709 / 2,787 |
| 5 | 626 / 3,104 | 556 / 2,585 | 1,150 / 3,047 | 616 / 2,722 | 595 / 2,697 |
| 6 | 638 / 3,136 | 581 / 2,701 | 520 / 2,610 | 443 / 2,614 | 520 / 2,610 |
| 7 | 660 / 3,136 | 613 / 2,738 | 771 / 2,841 | 551 / 2,711 | 590 / 2,740 |
| 8 | 719 / 3,138 | 560 / 2,720 | 376 / 2,473 | 682 / 2,771 | 365 / 2,440 |
| 9 | 722 / 3,145 | 600 / 2,670 | 513 / 2,562 | 576 / 2,492 | 513 / 2,562 |
| 10 | 627 / 3,103 | 546 / 2,709 | 498 / 2,572 | 615 / 2,745 | 448 / 2,674 |

interlock violations: {'webster': 0, 'truth': 0, 'vision:itms6_640:failsafe:nogap': 0, 'vision:itms6_640:failsafe:count_v2': 0, 'vision:itms6_640:failsafe': 0}; fixed-time fallback ticks: {'webster': 0, 'truth': 0, 'vision:itms6_640:failsafe:nogap': 1, 'vision:itms6_640:failsafe:count_v2': 1, 'vision:itms6_640:failsafe': 1}
