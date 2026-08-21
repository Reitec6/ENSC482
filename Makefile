#use 'make' or mingw32-make 
all: run

#Compile C++ udp receiver
compile:
	g++ -o udp_receiver udp_receiver.cpp -lws2_32

#Run .exe and .py after compilation
#terminal output cmd /c start, udp server setup on one console and .py script on other
run: compile
	@echo "Starting C++ Receiver"
	cmd /c start cmd /k "udp_receiver.exe"
	@echo "Starting MediaPipe"
	cmd /c start cmd /k "python mp_sender.py"

# clean for windows, -rm for linux
clean:
	del udp_receiver.exe