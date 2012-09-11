#!/usr/bin/env python
#
# ULG - Universal Looking Glass
# by Tomas Hlavacek (tomas.hlavacek@nic.cz)
# last udate: June 21 2012
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# Imports
import os
import socket
import re

import defaults

import ulgmodel

IPV46_SUBNET_REGEXP = '^[0-9a-fA-F:\.]+(/[0-9]{1,2}){0,1}$'

BIRD_SOCK_HEADER_REGEXP='^([0-9]+)[-\s](.+)$'
BIRD_SOCK_REPLY_END_REGEXP='^([0-9]+)\s*(\s.*)?$'

BIRD_SHOW_PROTO_LINE_REGEXP='^\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)(\s+([^\s].+)){0,1}\s*$'
BIRD_SHOW_PROTO_HEADER_REGEXP='^\s*(name)\s+(proto)\s+(table)\s+(state)\s+(since)\s+(info)\s*$'

bird_sock_header_regexp = re.compile(BIRD_SOCK_HEADER_REGEXP)
bird_sock_reply_end_regexp = re.compile(BIRD_SOCK_REPLY_END_REGEXP)


def parseBirdShowProtocols(text):
    def parseShowProtocolsLine(line):
        sh_proto_line_regexp = re.compile(BIRD_SHOW_PROTO_LINE_REGEXP)
        m = sh_proto_line_regexp.match(line)
        if(m):
            res = list(m.groups()[0:5])
            if(m.group(6)):
                res.append(m.group(6))

            return res
        else:
            ulgmodel.log("WARN: bird.parseShowProtocolsLine failed to match line: "+line)
            return None


    header = []
    table = []
    for l in str.splitlines(text):
        if(re.match('^\s*$',l)):
            continue
        
        hm = re.match(BIRD_SHOW_PROTO_HEADER_REGEXP,l)
        if(hm):
            header = hm.groups()
        else:
            pl = parseShowProtocolsLine(l)
            if(pl):
                table.append(pl)
            else:
                ulgmodel.log("ulgbird.parseBirdShowProtocols skipping unparsable line"+l)

    return (header,table)


# classes

class BirdShowProtocolsCommand(ulgmodel.TextCommand):
    COMMAND_TEXT = 'show protocols'

    def __init__(self,name=None,show_proto_all_command=None,proto_filter=None):
        ulgmodel.TextCommand.__init__(self,self.COMMAND_TEXT,param_specs=[],name=name)
        self.show_proto_all_command = show_proto_all_command
        self.fltr = proto_filter

    def _getPeerURL(self,decorator_helper,router,peer_id):
        if decorator_helper and self.show_proto_all_command:
            return decorator_helper.getRuncommandURL({'routerid':str(decorator_helper.getRouterID(router)),
                                                      'commandid':str(decorator_helper.getCommandID(router,self.show_proto_all_command)),
                                                      'param0':peer_id})
        else:
            return None

    def _getPeerTableCell(self,decorator_helper,router,peer_id):
        url = self._getPeerURL(decorator_helper,router,peer_id)
        if(url):
            return decorator_helper.ahref(url,peer_id)
        else:
            return peer_id

    def _decorateTableLine(self,table_line,router,decorator_helper):
        def _getTableLineColor(state):
            if(state == 'up'):
                return ulgmodel.TableDecorator.GREEN
            elif(state == 'start'):
                return ulgmodel.TableDecorator.YELLOW
            else:
                return ulgmodel.TableDecorator.RED

        color = _getTableLineColor(table_line[3])
        tl = [(self._getPeerTableCell(decorator_helper,router,table_line[0]),color),
              (table_line[1],color),
              (table_line[2],color),
              (table_line[3],color),
              (table_line[4],color),
              ]
        if(len(table_line)>5):
            tl.append((table_line[5],color))

        return tl


    def decorateResult(self,result,router=None,decorator_helper=None):
        if((not router) or (not decorator_helper)):
            return "<pre>\n%s\n</pre>" % result
        else:
            pr = parseBirdShowProtocols(result)
            table_header = pr[0]
            table = []

            for tl in pr[1]:
                # skip when there is a filter and it does not match the protocol type
                if(self.fltr) and (not re.match(self.fltr,tl[1])):
                    continue
                table.append(self._decorateTableLine(tl,router,decorator_helper))

            return ulgmodel.TableDecorator(table,table_header).decorate()


class BirdBGPPeerSelectCommand(ulgmodel.TextCommand):
    """ Abstract class for all BIRD BGP peer-specific commands """

    def __init__(self,peers,name=None):
        peer_param = ulgmodel.SelectionParameter([tuple((p,p,)) for p in peers],
                                                 name=defaults.STRING_PEERID)
        ulgmodel.TextCommand.__init__(self,self.COMMAND_TEXT,param_specs=[peer_param],name=name)

class BirdShowProtocolsAllCommand(BirdBGPPeerSelectCommand):
    COMMAND_TEXT = 'show protocols all %s'

class BirdShowRouteExportCommand(BirdBGPPeerSelectCommand):
    COMMAND_TEXT = 'show route export %s'

class BirdShowRouteProtocolCommand(BirdBGPPeerSelectCommand):
    COMMAND_TEXT = 'show route protocol %s'

class BirdShowRouteAllCommand(ulgmodel.TextCommand):
    COMMAND_TEXT = 'show route all %s'

    def __init__(self,name=None):
        ulgmodel.TextCommand.__init__(self,self.COMMAND_TEXT,param_specs=[
                ulgmodel.TextParameter(pattern=IPV46_SUBNET_REGEXP,name=defaults.STRING_IPSUBNET)
                ],
                                      name=name)


class BirdRouterLocal(ulgmodel.LocalRouter):
    RESCAN_PEERS_COMMAND = 'show protocols'
    DEFAULT_PROTOCOL_FLTR = '^(Kernel|Device|Static|BGP).*$'

    def __init__(self,sock=defaults.default_bird_sock,commands=None,proto_fltr=None):
        super(self.__class__,self).__init__()
        self.sock = sock
        self.setName('localhost')
        if(proto_fltr):
            self.proto_fltr = proto_fltr
        else:
            self.proto_fltr = self.DEFAULT_PROTOCOL_FLTR

        # command autoconfiguration might run only after other parameters are set
        if(commands):
            self.setCommands(commands)
        else:
            self.setCommands(self._getDefaultCommands())

    def _getDefaultCommands(self):
        sh_proto_all = BirdShowProtocolsAllCommand(self.getBGPPeers())
        sh_proto_route = BirdShowRouteProtocolCommand(self.getBGPPeers())
        sh_proto_export = BirdShowRouteExportCommand(self.getBGPPeers())
        return [BirdShowProtocolsCommand(show_proto_all_command=sh_proto_all, proto_filter = self.proto_fltr),
                sh_proto_all,
                sh_proto_route,
                sh_proto_export,
                BirdShowRouteAllCommand(),
                ulgmodel.TextCommand('show status'),
                ulgmodel.TextCommand('show memory')
                ]

    def runRawCommand(self,command,outfile):
        def parseBirdSockLine(line):
            hm = bird_sock_header_regexp.match(line)
            if(hm):
                # first line of the reply
                return (int(hm.group(1)),hm.group(2))

            em = bird_sock_reply_end_regexp.match(line)
            if(em):
                # most likely the last line of the reply
                return (int(em.group(1)),None)

            if(line[0] == '+'):
                # ignore async reply
                return (None,None)

            if(line[0] == ' '):
                # return reply line as it is (remove padding)
                return (None,line[1:])

            raise Exception("Can not parse BIRD output line: "+line)

        def isBirdSockReplyEnd(code):
            if(code==None):
                return False

            if(code == 0):
                # end of reply
                return True
            elif(code == 13):
                # show status last line
                return True
            elif(code >= 9000):
                # probably error
                return True
            else:
                return False

#        try:
        # open socket to BIRD
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(defaults.default_bird_sock_timeout)
        s.connect(self.sock)

        # cretate FD for the socket
        sf=s.makefile()

        # wait for initial header
        l = sf.readline()

        # send the command string
        sf.write(command+"\n")
        sf.flush()

        # read and capture lines until the output delimiter string is hit
        while(True):
            l = sf.readline()

            ulgmodel.debug("Raw line read: " + l)

            # process line according to rules take out from the C code
            lp = parseBirdSockLine(l)
            if(isBirdSockReplyEnd(lp[0])):
                # End of reply (0000 or similar code)
                ulgmodel.debug("End of reply. Code="+str(lp[0]))

                if(lp[1]):
                    ulgmodel.debug("Last read line after normalize: " + lp[1])
                    outfile.write(lp[1]+'\n')
                break
            else:
                if(lp[1]):
                    ulgmodel.debug("Read line after normalize: " + lp[1])
                    outfile.write(lp[1]+'\n')
                else:
                    ulgmodel.debug("Read line was empty after normalize.")

        # close the socket and return captured result
        s.close()

#        except socket.timeout as e:
#            # catch only timeout exception, while letting other exceptions pass
#            outfile.result(defaults.STRING_SOCKET_TIMEOUT)

    def getForkNeeded(self):
        return False


    def rescanPeers(self):
        res = self.runRawSyncCommand(self.RESCAN_PEERS_COMMAND)
        psp = parseBirdShowProtocols(res)

        peers = []
        for pspl in psp[1]:
            if(re.match(self.proto_fltr,pspl[1])):
                peers.append(pspl[0])

        return peers


    def getBGPPeers(self):
        return self.rescanPeers()

    def getBGPIPv6Peers(self):
        return self.bgp_ipv6_peers

