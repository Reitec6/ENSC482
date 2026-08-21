//winsock library for network server
#pragma comment(lib, "ws2_32.lib")

#include <iostream>
#include <winsock2.h>
#include <ws2tcpip.h>

using namespace std;

#define UDP_PORT 5005
//json string
#define BUFFER_SIZE 4096

int main() {
    //Winsock
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        cerr << "WSAStartup failed." << endl;
        return 1;
    }

    //UDP Socket
    SOCKET recvSocket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (recvSocket == INVALID_SOCKET) {
        cerr << "Socket creation failed. Error: " << WSAGetLastError() << endl;
        WSACleanup();
        return 1;
    }

    
    sockaddr_in recvAddr;
    recvAddr.sin_family = AF_INET;
    recvAddr.sin_port = htons(UDP_PORT);
    recvAddr.sin_addr.s_addr = htonl(INADDR_ANY);
    //Connect UDP port and errror output if bind failed
    if (bind(recvSocket, (SOCKADDR*)&recvAddr, sizeof(recvAddr)) == SOCKET_ERROR) {
        cerr << "Bind failed. Error: " << WSAGetLastError() << endl;
        closesocket(recvSocket);
        WSACleanup();
        return 1;
    }

    //successful connection
    cout << "C++ receiver UDP startup on port: " << UDP_PORT << "..." << endl;


    //Server listening connection loop
    char receiveBuffer[BUFFER_SIZE];
    sockaddr_in senderAddr;
    int senderAddrSize = sizeof(senderAddr);

    while (true) {
        //Buffer clear
        memset(receiveBuffer, 0, BUFFER_SIZE);

        //received bytes if hand was detected
        int bytesReceived = recvfrom(recvSocket, receiveBuffer, BUFFER_SIZE - 1, 0, 
                                     (SOCKADDR*)&senderAddr, &senderAddrSize);

        if (bytesReceived == SOCKET_ERROR) {
            cerr << "recvfrom failed. Error: " << WSAGetLastError() << endl;
            break;
        }

        //cout of coordinates from JSON
        cout << "Received " << bytesReceived << " bytes from Python." << endl;
        cout << "Hand Coordinates JSON: " << receiveBuffer << endl;
        
    }

    //Deinitialization
    closesocket(recvSocket);
    WSACleanup();
    return 0;
}