"""Default pattern templates for the File Reorganizer."""

DEFAULT_SPECIFIC = (
    "$set(A_AlbumArtist,$swapprefix($if2(%albumartist%,%artist%),A,An,The))\n"
    "$set(A_AlbumType,$if($eq(%A_AlbumArtist%,Various Artists),"
    "Various Artists,Specific Artists))\n"
    "$set(A_AlbumYear,$if2(%originalyear%,$left(%originaldate%,4),$left(%date%,4),0000))\n"
    "$set(A_AlbumTitle,$if(%album%,%album%,Unknown Album))\n"
    "$set(A_AlbumChar,$left($swapprefix(%A_AlbumArtist%,A,An,The),1))\n"
    "\n"
    "%A_AlbumType%/\n"
    "\n"
    "$if($eq(%A_AlbumType%,Specific Artists),\n"
    "   %A_AlbumChar%/\n"
    "   %A_AlbumArtist%/\n"
    "   %A_AlbumYear% - %A_AlbumTitle%/\n"
    "   %discnumber%-$num(%tracknumber%,2) %title%)\n"
    "\n"
    "$if($eq(%A_AlbumType%,Various Artists),\n"
    "   %A_AlbumYear% - %A_AlbumTitle%/\n"
    "   %discnumber%-$num(%tracknumber%,2) %artist% - %title%)"
)

DEFAULT_VARIOUS = (
    "$set(A_AlbumYear,$if2(%originalyear%,$left(%originaldate%,4),$left(%date%,4),0000))\n"
    "$set(A_AlbumTitle,$if(%album%,%album%,Unknown Album))\n"
    "\n"
    "%A_AlbumYear% - %A_AlbumTitle%/\n"
    "%discnumber%-$num(%tracknumber%,2) %artist% - %title%"
)
