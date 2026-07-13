set target_part 5CEBA4F23C8

if {[catch {get_part_info -family $target_part} family]} {
    puts stderr "cannot resolve target part $target_part: $family"
    exit 69
}

if {$family ne "Cyclone V"} {
    puts stderr "target part $target_part resolved to unexpected family: $family"
    exit 70
}

puts "verified Quartus device database: $target_part -> $family"
exit 0
