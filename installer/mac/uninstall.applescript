set sastre_title to "Sastre-Pro"
set userResponse to display dialog "Are you sure you want to uninstall the sastre-pro application?" with title sastre_title buttons {"Cancel", "Uninstall"} default button "Uninstall" with icon caution
set userPassword to ""

on fetchLastLines(inputText)
	set lineList to paragraphs of inputText
    set lastLine to item -1 of lineList
	return lastLine
end fetchLastLines

if button returned of userResponse is "Uninstall" then
	set maxAttempts to 3
	set attemptCount to 0
	
	repeat maxAttempts times
		set passwordPrompt to display dialog "Please enter your password to uninstall the sastre-pro application:" default answer "" with hidden answer with title sastre_title
		set userPassword to text returned of passwordPrompt
		set sudoCmd to "echo \"" & userPassword & "\" | sudo -S ls"
		
		try
			do shell script sudoCmd
			exit repeat 
		on error errMsg
			set attemptCount to attemptCount + 1
			if attemptCount = maxAttempts then
				display dialog "Number of attempts exceeded. Exiting." with title sastre_title buttons {"OK"} default button "OK" with icon stop
				return
			else
				display dialog "Invalid password. Please try again. Attempt " & attemptCount & " of " & maxAttempts with title sastre_title buttons {"OK"} default button "OK" with icon stop
			end if
		end try
	end repeat
	
	try
		do shell script "echo \"" & userPassword & "\" | sudo -S bash ~/sastre-pro/uninstall.sh 2>&1"
	on error errMsg
        set lastErrorMessage to fetchLastLines(errMsg)
		display dialog "Failed to uninstall the sastre-pro application. Error: " & lastErrorMessage with title sastre_title buttons {"OK"} default button "OK" with icon stop
	end try
else
	display dialog "Sastre-Pro application uninstallation canceled." with title sastre_title buttons {"OK"} default button "OK" with icon stop
end if