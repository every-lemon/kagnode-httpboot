"""KagNode HTTP Boot startup identity and progress, with plain text fallback."""
import os
import subprocess
import sys
import time


# Generated from the canonical mark and original block lettering.
LOGO_DISPLAY = '        #########\n     ############         ##      ##    ######      ########  ##      ##    ######    ########    ##########\n   #############          ##    ##    ##      ##  ##          ####    ##  ##      ##  ##      ##  ##\n  ##############  ###     ##  ##      ##      ##  ##          ####    ##  ##      ##  ##      ##  ##\n  #############   ####    ####        ##########  ##  ######  ##  ##  ##  ##      ##  ##      ##  ########\n  #############  #####    ##  ##      ##      ##  ##      ##  ##    ####  ##      ##  ##      ##  ##\n  ############   ####     ##    ##    ##      ##  ##      ##  ##    ####  ##      ##  ##      ##  ##\n   ###########   ###      ##      ##  ##      ##    ########  ##      ##    ######    ########    ##########  ##\n     ########\n'

LOGO_WIDE = '        #########\n     ############        #   #  ###   #### #   #  ###  ####  #####\n   #############         #  #  #   # #     ##  # #   # #   # #\n  ##############  ###    # #   #   # #     ##  # #   # #   # #\n  #############   ####   ##    ##### # ### # # # #   # #   # ####\n  #############  #####   # #   #   # #   # #  ## #   # #   # #\n  ############   ####    #  #  #   # #   # #  ## #   # #   # #\n   ###########   ###     #   # #   #  #### #   #  ###  ####  ##### #\n     ########\n'

LOGO_COMPACT = '        #########\n     ############\n   #############\n  ##############  ###\n  #############   ####\n  #############  #####\n  ############   ####\n   ###########   ###\n     ########\n\n  KagNode.\n'

LOGO_SMALL = '       #######\n    ##########\n   ##########  #\n  ###########  ##\n  ##########  ####\n  ##########  ###\n   #########  ###\n     ######\n\n  KagNode.\n'

def startup_banner(columns=80):
    for art in (LOGO_DISPLAY, LOGO_WIDE, LOGO_COMPACT, LOGO_SMALL):
        if max(map(len, art.splitlines()), default=0) < columns:
            return art
    if columns > 8: return 'KagNode.\n'
    if columns > 2: return 'KN\n'
    return ''

def terminal_banner(columns=80, color=False, blocks=False):
    art=startup_banner(columns)
    if not color:return art.replace('#','█') if blocks else art
    width=max(map(len,art.splitlines()),default=0)
    cut=26 if width>90 else 25 if width>45 else width
    rows=[]
    for line in art.splitlines():
        left,right=line[:cut],line[cut:]
        if blocks:left,right=left.replace('#','█'),right.replace('#','█')
        rows.append('\033[94m'+left+'\033[97m'+right+'\033[0m')
    return '\n'.join(rows)+('\n' if rows else '')


class Progress:
    def __init__(self):
        try: columns=os.get_terminal_size(sys.stdout.fileno()).columns or 80
        except (OSError,ValueError,AttributeError): columns=80
        color=sys.stdout.isatty() and os.environ.get('TERM','') not in ('','dumb') and 'NO_COLOR' not in os.environ
        blocks=sys.stdout.isatty() and os.environ.get('TERM','') not in ('','dumb') and str(getattr(sys.stdout,'encoding','')).lower().replace('-','')=='utf8'
        print('\n'+terminal_banner(columns,color,blocks)+'\n  HTTP Boot\n',flush=True)
        self.process=None;self.console=None;self.last=0;self.started=time.monotonic();self.label='Preparing startup'
        self.interactive=sys.stdin.isatty() and os.environ.get('TERM','')!='dumb'
    def stage(self,label):
        self.close();self.label=label;self.started=time.monotonic();self.last=0
        if not self.interactive:print(label,flush=True)
        else:
            with open(os.ttyname(sys.stdin.fileno()) if sys.stdin.isatty() else '/dev/console','w') as console:
                subprocess.run(['whiptail','--title','KagNode. HTTP Boot','--infobox',label,'10','78'],stdout=console,stderr=console,check=False)
    def message(self,text):
        self.stage(text)
    def progress(self,**values):
        now=time.monotonic()
        done,total=values['bytes_done'],values['bytes_total']
        if now-self.last<0.2 and done!=total:return
        self.last=now;elapsed=int(now-self.started);eta=values.get('eta_seconds')
        line=f"{self.label}\n{done/1024**2:.1f} / {total/1024**2:.1f} MiB | {values.get('bytes_per_second',0)/1024**2:.1f} MiB/s\nElapsed {elapsed}s | ETA {int(eta) if eta is not None else 'unknown'}s"
        if not self.interactive:print(line.replace('\n',' | '),flush=True);return
        try:
            if self.process is None:
                self.console=open(os.ttyname(sys.stdin.fileno()) if sys.stdin.isatty() else '/dev/console','w')
                self.process=subprocess.Popen(['whiptail','--title','KagNode. HTTP Boot','--gauge',line,'12','78','0'],stdin=subprocess.PIPE,stdout=self.console,stderr=self.console,text=True)
            percent=min(100,int(done*100/total)) if total else 0
            self.process.stdin.write(f'XXX\n{percent}\n{line}\nXXX\n');self.process.stdin.flush()
        except (OSError,BrokenPipeError):
            self.close();self.interactive=False;print(line,flush=True)
    def close(self):
        if self.process:
            try:self.process.stdin.close();self.process.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):self.process.terminate();self.process.wait(timeout=3)
            self.process=None
        if self.console:self.console.close();self.console=None
