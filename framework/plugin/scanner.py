#!/usr/bin/env python
'''
owtf is an OWASP+PTES-focused try to unite great tools and facilitate pen testing
Copyright (c) 2011, Abraham Aranguren <name.surname@gmail.com> Twitter: @7a_ http://7-a.org
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the copyright owner nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The scan_network scans the network for different ports and call network plugins for different services running on target
'''
import sys
import os
import re
import socket
import logging

SCANS_FOLDER="scans" # Folder under which all scans will be saved
PING_SWEEP_FILE=SCANS_FOLDER+"/00_ping_sweep"
DNS_INFO_FILE= SCANS_FOLDER+"/01_dns_info"
FAST_SCAN_FILE=SCANS_FOLDER+"/02_fast_scan"
STD_SCAN_FILE=SCANS_FOLDER+"/03_std_scan"
FULL_SCAN_FILE=SCANS_FOLDER+"/04_full_scan"


class Scanner:

    def __init__(self,CoreObj):
        self.core = CoreObj
        self.core.Shell.shell_exec("mkdir "+SCANS_FOLDER)

    def ping_sweep(self,target,scantype):
        if scantype == "full":
            logging.info("Performing Intense Host discovery")
            self.core.Shell.shell_exec("nmap -n -v -sP -PE -PP -PS21,22,23,25,80,443,113,21339 -PA80,113,443,10042 --source_port 53 "+ target +" -oA "+ PING_SWEEP_FILE)

        if scantype=="arp":
            logging.info("Performing ARP host discovery")
            self.core.Shell.shell_exec("nmap -n -v -sP -PR "+ target +" -oA "+ PING_SWEEP_FILE)

        self.core.Shell.shell_exec("grep Up "+PING_SWEEP_FILE+".gnmap | cut -f2 -d\" \" > "+ PING_SWEEP_FILE+".ips")

    def dns_sweep(self,file_with_ips,file_prefix):
        logging.info("Finding misconfigured DNS servers that might allow zone transfers among live ips ..")
        self.core.Shell.shell_exec("nmap -PN -n -sS -p 53 -iL "+file_with_ips+" -oA "+file_prefix)

# Step 2 - Extract IPs
        dns_servers=file_prefix+".dns_server.ips"
        self.core.Shell.shell_exec("grep \"53/open/tcp\" "+file_prefix+".gnmap | cut -f 2 -d \" \" > "+dns_servers)
        file = self.core.open(dns_servers)
        domain_names=file_prefix+".domain_names"
        self.core.Shell.shell_exec("rm -f "+domain_names)
        num_dns_servers = 0
        for line in file:
            if line.strip('\n'):
                dns_server = line.strip('\n')
                self.core.Shell.shell_exec("host "+dns_server+" "+dns_server+" | grep 'domain name' | cut -f 5 -d' ' | cut -f 2,3,4,5,6,7 -d. | sed 's/\.$//' >> "+domain_names)
                num_dns_servers = num_dns_servers+1
        try:
            file = self.core.open(domain_names, owtf_clean=False)
        except IOError:
            return

        for line in file:
            domain = line.strip('\n')
            raw_axfr=file_prefix+"."+dns_server+"."+domain+".axfr.raw"
            self.core.Shell.shell_exec("host -l "+domain+" "+dns_server+" | grep "+domain+" > "+raw_axfr)
            success=self.core.Shell.shell_exec("wc -l "+raw_axfr+" | cut -f 1  -d ' '")
            if success > 3:
                logging.info("Attempting zone transfer on $dns_server using domain "+domain+".. Success!")

                axfr=file_prefix+"."+dns_server+"."+domain+".axfr"
                self.core.Shell.shell_exec("rm -f "+axfr)
                logging.info(self.core.Shell.shell_exec("grep 'has address' "+raw_axfr+" | cut -f 1,4 -d ' ' | sort -k 2 -t ' ' | sed 's/ /#/g'"))
            else:
                logging.info("Attempting zone transfer on $dns_server using domain "+domain+"  .. Success!")
                self.core.Shell.shell_exec("rm -f "+raw_axfr)
        if num_dns_servers==0:
            return

    def scan_and_grab_banners(self,file_with_ips,file_prefix,scan_type,nmap_options):
        if scan_type == "tcp":
            logging.info("Performing TCP portscan, OS detection, Service detection, banner grabbing, etc")
            self.core.Shell.shell_exec("nmap -PN -n -v --min-parallelism=10 -iL "+file_with_ips+" -sS -sV -O  -oA "+file_prefix+".tcp "+nmap_options)
            self.core.Shell.shell_exec("amap -1 -i "+file_prefix+".tcp.gnmap -Abq -m -o "+file_prefix+".tcp.amap -t 90 -T 90 -c 64")

        if scan_type=="udp":
               logging.info("Performing UDP portscan, Service detection, banner grabbing, etc")
               self.core.Shell.shell_exec("nmap -PN -n -v --min-parallelism=10 -iL "+file_with_ips+" -sU -sV -O -oA "+file_prefix+".udp "+nmap_options)
               self.core.Shell.shell_exec("amap -1 -i "+file_prefix+".udp.gnmap -Abq -m -o "+file_prefix+".udp.amap")


    def get_nmap_services_file(self):
        return '/usr/share/nmap/nmap-services'

    def get_ports_for_service(self,service, protocol):
        regexp = '(.*?)\t(.*?/.*?)\t(.*?)($|\t)(#.*){0,1}'
        re.compile(regexp)
        list = []
        f = self.core.open(self.get_nmap_services_file())
        for line in f.readlines():
            if line.lower().find(service) >= 0:
                match = re.findall(regexp, line)
                if match:
                    port = match[0][1].split('/')[0]
                    prot = match[0][1].split('/')[1]
                    if (not protocol or protocol == prot) and port not in list:
                        list.append(port)
        f.close()
        return list

    def target_service(self, nmap_file, service):
        ports_for_service = self.get_ports_for_service(service,"")
        f = self.core.open(nmap_file.strip())
        response = ""
        for host_ports in re.findall('Host: (.*?)\tPorts: (.*?)[\t\n]', f.read()):
            host = host_ports[0].split(' ')[0] # Remove junk at the end
            ports = host_ports[1].split(',')
            for port_info in ports:
                if len(port_info) < 1:
                    continue;
                chunk = port_info.split('/')
                port = chunk[0].strip()
                port_state = chunk[1].strip()
                if port_state in ['closed', 'filtered']:
                    continue; # No point in wasting time probing closed/filtered ports!! (nmap sometimes adds these to the gnmap file for some reason ..)
                try:
                    prot = chunk[2].strip()
                except:
                        continue;
                if port in ports_for_service:
                     response = response + host+":"+port+":"+prot+"##"
        f.close()

        return response


    def probe_service_for_hosts(self,nmap_file,target):
        services = []
        #get all available plugins from net plugin order file
        net_plugins= self.core.Config.Plugin.GetOrder("net")
        for plugin in net_plugins:
            services.append(plugin['Name'])
        services.append("http")
        total_tasks=0
        tasklist=""
        plugin_list = []
        http = []
        for service in services:
            if plugin_list.count(service)>0:
                continue
            tasks_for_service = len(self.target_service(nmap_file,service).split("##"))-1
            total_tasks = total_tasks+tasks_for_service
            tasklist=tasklist+" [ "+service+" - "+str(tasks_for_service)+" tasks ]"
            for line in self.target_service(nmap_file,service).split("##"):
                if line.strip("\n"):
                    ip = line.split(":")[0]
                    port = line.split(":")[1]
                    plugin_to_invoke = service
                    service1 = plugin_to_invoke
                    self.core.Config.Set(service1.upper()+"_PORT_NUMBER",port)
                    if(service != 'http'):
                        plugin_list.append(plugin_to_invoke)
                    else:
                        self.core.PluginHandler.OnlyPluginsSet = 0;
                        http.append(port)
                    logging.info("we have to probe "+str(ip)+":"+str(port)+" for service "+plugin_to_invoke)
        self.core.PluginHandler.OnlyPluginsList = self.core.PluginHandler.ValidateAndFormatPluginList(plugin_list)
        self.core.PluginHandler.OnlyPluginsSet = max(1,len(plugin_list))
        return http

    def scan_network(self,target):
        self.ping_sweep(target.split("//")[1],"full")
        self.dns_sweep(PING_SWEEP_FILE+".ips",DNS_INFO_FILE)

    def probe_network(self,target,protocol,port):
        self.scan_and_grab_banners(PING_SWEEP_FILE+".ips",FAST_SCAN_FILE,protocol,"-p "+port)
        return self.probe_service_for_hosts(FAST_SCAN_FILE+"."+protocol+".gnmap",target.split("//")[1])
