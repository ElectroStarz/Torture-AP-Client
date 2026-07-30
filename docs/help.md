# ElectroStarz's Guide to Torture

Greetings, I assume you are here because you either typed /torture_help, or just saw this document in the Github repo.
Either way, here's a guide on how to use the client.

## Generating and connecting to a room
When using the Torture Client, you will be required to place a yaml for the torture client in your players folder. No
locations or items will be generated for it, this just makes sure no one goes into random multiworlds using this. Once
generated and hosted, you connect like you would with any other client, type in the server address, port and the
torture client slot name.

Upon connecting, if you haven't already done so, you will see a prompt to either make a password or enter a password.
This password can be changed with /set_password

This client does require admin permissions to give out traps. You can set the server password in the console by doing /option
server_password {password}. Then in the client you can do !admin login {password}

***THE TORTURE CLIENT DOES NOT GUARANTEE THAT A PLAYER CANNOT USE IT HOWEVER ANY SECURITY SUGGESTIONS WILL BE GLADLY
ACCEPTED***

## Interfacing with the client
As usual, you have every feature the text client has, just a normal client. Or is it? Like UT, you'll see there is a new
tab in the top, "Torture Dashboard". It's recommended to have the client be larger than usual due to my poor kivy
skills... But anyway, on the left you will see multiworld information. If you have any suggestions as to what should be
there, please do say.

On the right you will see a few boxes. The first 2 are to send a deathlink, with the text input being the reason and the
box being the send box (Note, the slot name is NOT included in the reason, you will have to type something like "I hate
you all"). 

Below that there are the send traps options and the target player check boxes. This allows you to send traps to either
selected or random people. If you put a number without anyone selected, the client will select random people to send
traps to. If you have a number **and** selected people, it will pick [number]/[selected] people to send traps to. If you
have just selected people, it will send traps to them.

The trap sending may not be perfect, this checks the item_name_to_id in the datapackage for items that have the word
"Trap" (case-insensitive) in them.

Have a suggestion? Feel free to ping @electrostarz and I'll reply as soon as possible!