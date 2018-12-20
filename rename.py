import sys, glob, re, os
# Get the offset at the first command-line argument
offset = int(sys.argv[1]) 

# Go through the list of files in the reverse order
for name in reversed(glob.glob('*.?[!y]*')):
    # Extract the number and the rest of the name
    i, rest = re.findall("^(\d+)(.+)", name)[0]
    # Construct the new file name
    new_name = "{:05d}{}".format(int(i) + offset, rest)
    # Rename
    os.rename(name, new_name)


