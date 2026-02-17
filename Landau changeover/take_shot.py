#!/usr/bin/env python

from __future__ import print_function, absolute_import, division

import subprocess
import time
import gtk
import atexit
import MDSplus
import os 
import logging
import threading
import Queue

#import sys
#sys.path.insert(0, '/home/nikratio/pydevd')
#import pydevd
#pydevd.settrace('inspiron.ap.columbia.edu', stdoutToServer=True, stderrToServer=True)

gtk.gdk.threads_init()

log = logging.getLogger()

THREAD_TERMINATE_SENTINEL = object()

class CenteredHBox(gtk.HBox):

    def __init__(self, spacing):
        super(CenteredHBox, self).__init__(False, spacing)
        super(CenteredHBox, self).pack_start(gtk.Label(''), True, True)
        super(CenteredHBox, self).pack_end(gtk.Label(''), True, True)

    def pack_start(self, obj):
        super(CenteredHBox, self).pack_start(obj, False)

    def pack_end(self, obj):
        super(CenteredHBox, self).pack_end(obj, False)

class View(gtk.Window):

    def __init__(self, ctrl):
        super(View, self).__init__(gtk.WINDOW_TOPLEVEL)

        self.connect("delete_event", lambda *a: False)
        self.connect("destroy", self.main_quit)  ##use customized function
        self.set_border_width(10)
        self.set_title('MDSplus Dispatch Control')

        self.ctrl = ctrl
        self.shot_label = gtk.Label("Current Shot: %d" % ctrl.shotno)
        
        vbox = gtk.VBox(False, 10)
        self.setup_window(vbox)
        self.add(vbox)
        self.show_all()
        ctrl.view = self
    
    def main_quit(self,*arg,**arwg):  ### customize function for main_quit
        self.ctrl.close() ### close the controller properly
        gtk.main_quit()
            
    def setup_window(self, vbox):
        
        vbox.pack_start(self.shot_label)
        button = gtk.Button("New Shot")
        button.connect('clicked', lambda *a: self.ctrl.new_shot())
        hbox = CenteredHBox(False)
        hbox.pack_start(button)
        vbox.pack_start(hbox)
        vbox.pack_start(self.make_dispatch_box(self.ctrl), False)

    def make_dispatch_box(self, ctrl):
        table = gtk.Table(rows=2, columns=5)
        table.set_row_spacings(5)
        table.set_col_spacings(5)
        
        def prepare(*_):
            if ctrl.shot_taken:
                self.warn_dia('Warning',  'Shot already taken.')
                return                     
            try:
                ctrl.build()
                ctrl.init()
            except AbortCycle:
                pass

        button = gtk.Button("Prepare")
        button.connect('clicked', prepare)
        table.attach(button, 0, 2, 0, 1)

        button = gtk.Button("Fire")
        button.connect('clicked', lambda *a: ctrl.fire())
        table.attach(button, 2, 5, 0, 1)
        
        button = gtk.Button("Build")
        button.connect('clicked', lambda *a: ctrl.build())
        table.attach(button, 0, 1, 1, 2)

        button = gtk.Button("INIT")
        button.connect('clicked', lambda *a: ctrl.init())
        table.attach(button, 1, 2, 1, 2)

        button = gtk.Button("PULSE ON")
        button.connect('clicked', lambda *a: ctrl.pulse_on())
        table.attach(button, 2, 3, 1, 2)

        button = gtk.Button("STORE")
        button.connect('clicked', lambda *a: ctrl.store())
        table.attach(button, 3, 4, 1, 2)

        button = gtk.Button("ANALYSIS")
        button.connect('clicked', lambda *a: ctrl.analysis())
        table.attach(button, 4, 5, 1, 2)

        return table
        
    def yoc_dia(self, title, text):
        dialog = gtk.Dialog(title, self, gtk.DIALOG_MODAL,
                            (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                             gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        label = gtk.Label(text)
        label.show()
        # Bogus error
        #pylint: disable=E1101
        dialog.vbox.pack_start(label)
        response = dialog.run()
        dialog.destroy()
        self.process_pending_events()

        return response == gtk.RESPONSE_ACCEPT

    def yon_dia(self, title, text):
        dialog = gtk.Dialog(title, self, gtk.DIALOG_MODAL,
                            (gtk.STOCK_NO, gtk.RESPONSE_NO,
                             gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        label = gtk.Label(text)
        label.show()
        # Bogus error
        #pylint: disable=E1101
        dialog.vbox.pack_start(label)
        response = dialog.run()
        dialog.destroy()
        self.process_pending_events()

        return response == gtk.RESPONSE_ACCEPT
    
    def ok_dia(self, title, text):
        dialog = gtk.Dialog(title, self, gtk.DIALOG_MODAL,
                            (gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        label = gtk.Label(text)
        label.show()
        # Bogus error
        #pylint: disable=E1101
        dialog.vbox.pack_start(label)
        dialog.run()
        dialog.destroy()
        self.process_pending_events() 

    def warn_dia(self, title, text):
        dialog = gtk.Dialog(title, self, gtk.DIALOG_MODAL,
                            (gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        label = gtk.Label(text)
        label.show()
        # Bogus error
        #pylint: disable=E1101
        dialog.vbox.pack_start(label)
        dialog.run()
        dialog.destroy()
        self.process_pending_events()

    def process_pending_events(self):
        while gtk.events_pending():
            gtk.main_iteration ()


class Controller(object):
 
    # MDSplus requires access to protected members
    #pylint: disable=W0212
        
    def __init__(self, treename, base_port):
        super(Controller, self).__init__()
        self.treename = treename
        self.shotno =  MDSplus.Tree.getCurrent(treename)
        self.base_port = base_port
        self.model = MDSplus.Tree(self.treename, -1)
        self.jdispatcher = None
        self.jmonitor = None
        self.shot_taken = True
        self.db = None
        self.view = None
        self._cmd_queue=Queue.Queue()      ### queue to communicate with  cmd subtread
        ### sub thread that will be used for dispatching cmds
        self._cmd_subthread=threading.Thread(target=self.__cmd_thread_fn)
        
        # Someone may have messed with the shot number without creating
        # a shot
        while True:
            try:
                self.tree = MDSplus.Tree(self.treename, self.shotno)
                break
            except MDSplus._treeshr.TreeException as exc:
                if exc.args[0].startswith('%TREE-E-TreeFILE_NOT_FOUND'):
                    log.warn('Current shot %d has apparently not been taken, '
                             'reusing shot number', self.shotno)
                    self.shotno -= 1
                else:
                    raise
        self._cmd_subthread.start()    
    @property
    def current_model(self):
        return MDSplus.Tree(self.treename, self.shotno)

    def launch_dispatcher(self, tempdir, server):
        '''Launch Dispatcher and Monitor'''

        with open(os.path.join(tempdir, 'jDispatcher.properties'), 'w') as fh:
            fh.write(dispatcher_properties %
                     {'jDispatcher.port': 8001+self.base_port,
                      'jDispatcher.monitor_1.port': 8010+self.base_port,
		              'SERVER': server,
                      'jDispatcher.info_port': 8011 +self.base_port})

        logger = subprocess.Popen(['logger', '-t', 'jDispatcher', '-p', 'local0.info'],
                                  stdin=subprocess.PIPE)
        self.jdispatcher = subprocess.Popen(['jDispatcherIp', self.treename], 
                                            stderr=subprocess.STDOUT,
                                            cwd=tempdir, stdout=logger.stdin)
        atexit.register(self.jdispatcher.terminate)

        time.sleep(3)
        null = open('/dev/null', 'r+b')
        self.jmonitor = subprocess.Popen(['jDispatchMonitor', 
                                          'localhost:%d' % (8010 + self.base_port)],
                                         cwd=tempdir, stdout=null, stderr=null)
        atexit.register(self.jmonitor.terminate)

    def __cmd_thread_fn(self):
        '''function used by the cmd subprocess'''
        while(True):
            cmd=self._cmd_queue.get()
            if cmd is THREAD_TERMINATE_SENTINEL:
                break
            else:
                self.eval_tcl('dispatch/command/server=localhost:%d %s\n' 
                      % (8001+self.base_port, cmd))  
                
                
            
    def eval_tcl(self, cmd):
        MDSplus.Data.execute('tcl($)', cmd)

    def dispatch_cmd(self, cmd, sync=False):
        if sync:
            self.eval_tcl('dispatch/command/server=localhost:%d %s\n' 
                          % (8001+self.base_port, cmd))
        else:
            self._cmd_queue.put(cmd)

    def build(self):
        self.dispatch_cmd('set tree %s' % self.treename)
        self.dispatch_cmd('dispatch /build')

    def new_shot(self):  
        self.shotno += 1
        self.dispatch_cmd('set tree %s' % self.treename, sync=True)
        self.dispatch_cmd('create pulse %d' % self.shotno, sync=True)
        MDSplus.Tree.setCurrent(self.treename, self.shotno)
        self.view.shot_label.set_text('Current shot: %d' % self.shotno)
        self.shot_taken = False
        self.tree = MDSplus.Tree(self.treename, self.shotno)
            
    def init(self):
        self.dispatch_cmd('dispatch /phase INIT')

    def pulse_on(self):
        self.dispatch_cmd('dispatch /phase PULSE_ON')

    def store(self):
        MDSplus.event.Event.setevent('store_{0}'.format(self.treename))
        self.dispatch_cmd('dispatch /phase STORE')
        self.shot_taken = True                     

    def analysis(self):
        self.dispatch_cmd('dispatch /phase ANALYSIS')
        self.dispatch_cmd('close tree')

    def fire(self):
        try:    
            self.pulse_on()
            time.sleep(3)
            self.store()
            self.analysis()
        except AbortCycle:
            pass
            
    def close(self):
        # Signal command processing thread to terminate
        self._cmd_queue.put(THREAD_TERMINATE_SENTINEL)

class AbortCycle(Exception):
    '''Raised to abort the current cycle'''
    pass


dispatcher_properties = '''
#The port at which jDispatcherIp listens to incoming commands
jDispatcher.port = %(jDispatcher.port)d

#server classes and addresses
jDispatcher.server_1.class = SPITZER
jDispatcher.server_1.address = %(SERVER)s
jDispatcher.server_1.use_jserver = false

#default server id: used by jDispatcher when an unknown server is found
jDispatcher.default_server_idx = 1

#phase names and corresponding identifiers
jDispatcher.phase_1.id = 1
jDispatcher.phase_1.name = INIT
jDispatcher.phase_2.id = 2
jDispatcher.phase_2.name = PULSE_ON
jDispatcher.phase_3.id = 3
jDispatcher.phase_3.name = STORE
jDispatcher.phase_4.id = 4
jDispatcher.phase_4.name = ANALYSIS

# The ports used by jDispatcher to export information to jDispatchMonitor
jDispatcher.monitor_1.port = %(jDispatcher.monitor_1.port)d
jDispatcher.info_port = %(jDispatcher.info_port)d
'''

