set target_part 5CEBA4F23C8

if {[catch {get_part_info -family $target_part} family]} {
    puts stderr "cannot resolve target part $target_part: $family"
    exit 69
}

if {$family eq "Cyclone V"} {
    set family_name $family
} elseif {[catch {llength $family} family_count] || $family_count != 1} {
    puts stderr "target part $target_part resolved to unexpected family: $family"
    exit 70
} else {
    set family_name [lindex $family 0]
}
if {$family_name ne "Cyclone V"} {
    puts stderr "target part $target_part resolved to unexpected family: $family_name"
    exit 70
}

puts "verified Quartus device database: $target_part -> $family_name"
exit 0
