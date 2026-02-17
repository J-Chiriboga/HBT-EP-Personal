#!/usr/bin/env python

#if updating this program, be sure to have updated and run make_tree.py
#(if necessary) and generate a new shot number before committing changes
#(otherwise there will be conflicts with the look of last shot's display
#and the new look)

from __future__ import print_function, absolute_import

import gtk
import atexit
import shutil
import random
import tempfile
from hbtep import take_shot
from hbtep.take_shot import CenteredHBox
from Phidgets.Devices.InterfaceKit import InterfaceKit
from functools import partial
import MDSplus
import sys
import time
from argparse import ArgumentParser
import logging
import apsw

#Incorporates revisions for writing to the MySQL version of the meta data database
#Feb 2, 2015
#Nate Posey

import Mysql_meta

log = logging.getLogger()

class View(take_shot.View):
    
    def __init__(self, ctrl):
        self.pre_shot_fields = []
        self.pre_shot_node_fields = [] # like pre_shot_field. but change the tree node both for -1 and current one.
        self.post_shot_fields = []
        
        super(View, self).__init__(ctrl)
        
    def setup_window(self, vbox):
        super(View, self).setup_window(vbox)
        
        vbox.pack_start(self.make_settings_box(self.ctrl), False)
        vbox.pack_start(self.make_heading('Metadata:'), True, True)
        vbox.pack_start(self.make_pre_fields_box(self.ctrl), True, True)
        vbox.pack_start(self.make_comment_box(self.ctrl), True, True)
        vbox.pack_start(self.make_post_comment_box(self.ctrl), True, True)
        vbox.pack_start(self.make_post_fields_box(self.ctrl), True, True)
        
    def make_heading(self, name):
        label = gtk.Label('<b>%s</b>' % name)
        label.set_justify(gtk.JUSTIFY_LEFT)
        label.set_use_markup(True)
        outer = CenteredHBox(0)
        outer.pack_start(label)                                  
        return outer
        
    def make_comment_box(self, ctrl):

        cb = gtk.TextBuffer()
        try:
            cb.set_text(ctrl.tree.getNode('.metadata:comment').data())
        except:
            pass   
        textview = gtk.TextView(cb)
        textview.set_editable(False)
        textview.set_sensitive(False)
        textview.set_wrap_mode(gtk.WRAP_WORD)
        self.pre_shot_fields.append(textview)
        textview.connect('focus-out-event', 
                         lambda *a: ctrl.update_meta('comment', textview))
        
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.set_border_width(5)
        sw.add(textview)

        frame = gtk.Frame('Shot Description')
        frame.add(sw)

        return frame

    def make_post_comment_box(self, ctrl):

        cb = gtk.TextBuffer()
        try:
            cb.set_text(ctrl.tree.getNode('.metadata:post_comment').data())
        except:
            pass  
        textview = gtk.TextView(cb)
        textview.set_editable(True)
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textview.connect('focus-out-event', 
                         lambda *a: ctrl.update_meta('post_comment', textview))
        
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.set_border_width(5)
        sw.add(textview)
        self.post_shot_fields.append(textview)

        frame = gtk.Frame('Post Shot Remarks')
        frame.add(sw)

        return frame
    
    def make_settings_box(self, ctrl):

        toggle_settings = list(ctrl.get_toggle_settings())
        value_settings = list(ctrl.get_value_settings())

        if not toggle_settings and not value_settings:
            return gtk.VBox()
        
        table = gtk.Table(rows=(int((len(toggle_settings)+0.6)//2)
                                +len(value_settings)+1), columns=4)      
        table.set_col_spacings(10)

        label = gtk.Label('<b>Shot Settings:</b>')
        label.set_justify(gtk.JUSTIFY_LEFT)
        label.set_use_markup(True)
        table.attach(label, 1, 3, 0, 1)
        
        row = 1
        col = 0
        for (label, handler, state) in toggle_settings:
            button = gtk.CheckButton(label)       
            if state is None:
                button.set_inconsistent(True)
            else:
                button.set_active(state)
            button.connect("toggled", handler)
            button.set_sensitive(False)
            self.pre_shot_node_fields.append(button)
            table.attach(button, col, col+1, row, row+1)
            if col == 3:
                row += 1
                col = 0
            else:
                col += 1
        if col != 0:
            row += 1
        
        current_col = 0
        for (label, handler, value) in value_settings:
            label = gtk.Label(label)
            entry = gtk.Entry()
            entry.set_width_chars(30)
            entry.set_text(value)
            entry.connect("focus-out-event", handler, entry)
            entry.set_editable(False)
            entry.set_sensitive(False)
            self.pre_shot_node_fields.append(entry)
            table.attach(label, current_col + 0, current_col +1, row, row +1)
            table.attach(entry, current_col +1, current_col +2, row, row +1)
            current_col = (current_col + 2) % 4
            if current_col == 0:
                row += 1
                        
        outer = CenteredHBox(0)
        outer.pack_start(table)

        return outer

    def connect_update(self, node, widget):
        '''Helper function to deal with binding semantics'''
        widget.connect('focus-out-event', 
                       lambda *a: self.ctrl.update_meta(node, widget)) 
            
    def make_pre_fields_box(self, ctrl):
        fields = []
        
        # Pre-Shot information
        for (name, node) in [('Operator', 'operator'),
                             #('Hall Probe Position', 'hall_pos'),  #No longer in use 11/01/18
                             ('Bias Probe Position', 'bias_pos'),
                             #('Mach Probe Position', 'mach_pos'),  #No longer in use 11/01/18
                             ('TF [V]', 'tf_volts'),
                             ('VF EL [V]', 'vf_el_volts'),
                             ('VF ST [V]', 'vf_st_volts'),
                             ('OH EL [V]', 'oh_el_volts'), 
                             ('OH ST [V]', 'oh_st_volts'), 
                             ('OH Bias [V]', 'oh_b_volts'), 
                             ('SH ST [V]', 'sh_st_volts'), 
                             ('SH CB [V]', 'sh_cb_volts') ]:
            
            try:
                default = ctrl.tree.getNode('.metadata:%s' % node).data()
            except MDSplus._tdishr.TdiException:
                default = ''
            if not isinstance(default, str):
                default = '%d' % default
                
            entry = gtk.Entry()
            entry.set_width_chars(23)
            entry.set_text(default)
            entry.set_editable(False)
            entry.set_sensitive(False)
            label = gtk.Label(name)
            label.set_justify(gtk.JUSTIFY_RIGHT)
            self.pre_shot_fields.append(entry)
            self.connect_update(node, entry)
            fields.append((label, entry))
   
        table = gtk.Table(rows=len(fields), columns=4) 
        table.set_col_spacings(10)
        current_col = 0
        for (row, (label, entry)) in enumerate(fields):
            table.attach(label, current_col, current_col + 1, row/2, row/2 + 1, xoptions=gtk.FILL)
            table.attach(entry, current_col + 1, current_col + 2, row/2, row/2 + 1)
            current_col = (current_col + 2) %4
                             
        outer = CenteredHBox(0)
        outer.pack_start(table)

        return outer

    def make_post_fields_box(self, ctrl):
        fields = []
        
        # Pre-Shot information
        for (name, node) in [('Base pressure [nTorr]', 'pressure') ]:
            try:
                default = ctrl.tree.getNode('.metadata:%s' % node).data()
            except MDSplus._tdishr.TdiException:
                default = ''
            if not isinstance(default, str):
                default = '%.3g' % default
                
            entry = gtk.Entry()
       #     entry.set_width_chars(23)
            entry.set_text(default)
            label = gtk.Label(name)
            label.set_justify(gtk.JUSTIFY_LEFT)
            self.post_shot_fields.append(entry)            
            self.connect_update(node, entry)
            fields.append((label, entry))
   
        table = gtk.Table(rows=len(fields), columns=4) 
        table.set_col_spacings(10)
        for (row, (label, entry)) in enumerate(fields):
 #           table.attach(label, 0, 1, row, row+1, xoptions=gtk.FILL)
            table.attach(label, 0, 1, row, row+1, xoptions = gtk.FILL)
            table.attach(entry, 1, 3, row, row+1, xoptions = gtk.EXPAND)
                                  
        outer = CenteredHBox(0)
        outer.pack_start(table)
        
        return outer
 
                
class Controller(take_shot.Controller):
    
    def __init__(self, base_port):
        super(Controller, self).__init__('hbtep2', base_port)
            
        self.db = apsw.Connection('/opt/hbt/data/treedata.sqlite')
	#Revision
	try:
		user = "lyman"
		password = "stellarator"
		database = "shots"
		table = "highb"
	
		self.Mysql_db = Mysql_meta.Mysql_Data(user, password, database, table)
		log.debug("Connecting to MySQL database")
	except:
		log.debug("Error connecting to MySQL database!")
        #self.init_db()
        
    def init_db(self):
        '''Not normally called'''
        
        self.db.cursor().execute('''
        CREATE TABLE shots (
        shotno INTEGER PRIMARY KEY,
        date TEXT,
        operator TEXT,
        comment TEXT,
        post_comment TEXT,
        pressure REAL,
        oh_st_volts REAL,
        oh_el_volts REAL,
        vf_st_volts REAL,
        vf_el_volts REAL,
        oh_b_volts REAL,
        tf_volts REAL,
        bias_pos REAL,
	sh_st_time REAL,
        sh_st_volts REAL,
        sh_cb_volts REAL
        )''')
        
	#hall_pos REAL,  #No longer in use 11/01/18
        #mach_pos REAL,  #No longer in use 11/01/18
        
	self.db.cursor().execute('CREATE INDEX ix_date ON shots(date)')
        self.db.cursor().execute('CREATE INDEX ix_operator ON shots(operator)')
            
    def get_toggle_settings(self):
        # Invert list
#        h = {
#             'A14s': self.model.getNodeWild('.devices.*:A14*'),
#             'ACQs': self.model.getNodeWild('.devices.*:CPCI*'),
#             'North Rack': self.model.getNodeWild('.devices.north_rack:*'),
#             'South Rack': self.model.getNodeWild('.devices.south_rack:*'),
#             'West Rack': self.model.getNodeWild('.devices.west_rack:*'),
#             'Gas Puff': self.model.getNodeWild('.devices.basement:j221_09:output_03'),
#             'Shaping Coil': self.model.getNodeWild('.devices.basement:j221_02:output_06'),
#             }
        h = {
             'A14s': '.devices.*:A14*',
             'ACQs': '.devices.*:CPCI*',
             'North Rack': '.devices.north_rack:*',
             'South Rack': '.devices.south_rack:*',
             'West Rack': '.devices.west_rack:*',
             'Gas Puff': '.devices.basement:j221_09:output_03',
             'Shaping Coil': '.devices.basement:j221_02:output_06',
             }

        for (label, node_pattern) in h.iteritems():
            nodes = self.model.getNodeWild(node_pattern)
            some_active = any([ x.on for x in nodes])
            some_inactive = any([ not x.on for x in nodes])
            if some_active and some_inactive:
                state = None
            else:
                state = all([ x.on for x in nodes]) 
            yield (label, partial(self.toggle, nodes), state)
            
    def get_value_settings(self):
        hl = {
            'Gas Puff Time': '\\top.timing.gas_puff',
            'VF Start Time': '\\top.timing.banks.vf_st',
            'SH Start Time': '\\top.timing.banks.sh_st',
            'TS Laser Time': '\\top.timing.thomson.fire',
            }

        values = list()

        for (label, node_name) in hl.iteritems():
            values.extend([ (label+':',
                      partial(self.set_node, node_name),
                      self.model.getNode(node_name).record.decompile()) ]) 

        return values

    def set_node(self, node, widget, *_):
        self.model.getNode(node).record = MDSplus.Data.compile(widget.get_text())
        self.current_model.getNode(node).record = MDSplus.Data.compile(widget.get_text())
        
    def toggle(self, node_pattern, widget, *_):
        if widget.get_inconsistent():
            newstate = False
        else:
            newstate = widget.get_active()
            
        nodes = self.model.getNodeWild(node_pattern)
        for node in nodes:
            node.setOn(newstate)
        nodes = (self.current_model.getNodeWild(node_pattern))
        for node in nodes:
            node.setOn(newstate)

        widget.set_active(newstate)
        widget.set_inconsistent(False)

    def update_meta(self, nodename, widget):
        if isinstance(widget, gtk.TextView):
            buf = widget.get_buffer()
            value = buf.get_text(*buf.get_bounds())
        elif isinstance(widget, gtk.Entry):
            value = widget.get_text()            
        else:
            value = widget

        log.debug('Setting .metadata:%s to "%s"', nodename, value)
        if nodename == 'sh_st_time':
            node = self.tree.getNode('.timing.banks:sh_st')
        else:
            node = self.tree.getNode('.metadata:%s' % nodename)

        if value == '':
            value = None
        elif node.getUsage() == 'NUMERIC':
            value = float(value)
           
        # Nasty special case, sorry! 
        if nodename == 'pressure' and value:
            value *= 1e-9 # Convert from Nanotorr to torr
            
        node.record = value
        self.db.cursor().execute('UPDATE shots SET %s = ? WHERE shotno = ?' 
                                 % nodename, (value, self.shotno))   
				 
	
	#Revision: Update data for shotno in the MySQL database
	try:
		self.Mysql_db.update_meta(nodename, self.shotno, value)
		log.debug("Writing data for shotno %s" % self.shotno)
	except:
		log.debug("Error writing to MySQL database!")
        # Typically called as a handler, so we need to return
        # False
        return False
        
    def store(self):
        self.update_meta('date', time.strftime('%Y-%m-%d %H:%M'))
        #specifically added to save
        self.update_meta('sh_st_time',
                         self.tree.getNode('.timing.banks:sh_st').data())
        
        super(Controller, self).store()
        for field in self.view.pre_shot_fields:
            field.set_editable(False)
            field.set_sensitive(False)  

        for field in self.view.pre_shot_node_fields:
            if not isinstance(field,gtk.Button):
                field.set_editable(False)
            field.set_sensitive(False)  
 

        for field in self.view.post_shot_fields:
            field.set_editable(True)
            field.set_sensitive(True)       
  
    def new_shot(self):  
        super(Controller, self).new_shot()
         
        self.db.cursor().execute('INSERT INTO shots (shotno) VALUES(?)',
                                 (self.shotno,))
				 
	#Revision: Create new shot in the Mysql database
	try:
		self.Mysql_db.new_shot(self.shotno)
		log.debug("Creating  newshot for shotno %s" % self.shotno)
	except:
		log.debug("Error writing to MySQL database!")
        event = gtk.gdk.Event(gtk.gdk.FOCUS_CHANGE)
        for field in self.view.pre_shot_fields:
            field.set_editable(True)
            field.set_sensitive(True)  
            
            # Store metadata
            field.emit('focus-out-event', event)

        for field in self.view.pre_shot_node_fields:
            if not isinstance(field,gtk.Button):
                field.set_editable(True)
            field.set_sensitive(True)  
            
        for field in self.view.post_shot_fields:                     
            field.set_editable(False)
            field.set_sensitive(False)     
            if isinstance(field, gtk.TextView):
                field.get_buffer().set_text('')
            else:
                field.set_text('')
            
                                        
def parse_args(args):
    '''Parse command line'''

    parser = ArgumentParser(
        usage="%(prog)s [options] <shotno>\n"
              "%(prog)s --help")

    parser.add_argument("--debug", action="store_true", default=False,
                      help="Activate debugging output")
    parser.add_argument("--disable-phidget", action="store_true", default=False,
                      help="Do not auto trigger using Phidget")    
    parser.add_argument("--quiet", action="store_true", default=False,
                      help="Be really quiet")
    
    return parser.parse_args(args)


def init_logging(options):
    root_logger = logging.getLogger()
    formatter = logging.Formatter('%(message)s') 
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    if options.quiet:
        root_logger.setLevel(logging.WARN)
    elif options.debug:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    

def main(argv):
    options = parse_args(argv)
    init_logging(options)
    
    tempdir = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, tempdir)  
    ctrl = Controller(base_port=random.randint(100, 500))
    ctrl.launch_dispatcher(tempdir, 'spitzer:8002')
    view = View(ctrl)
    view.set_title('HBT-EP Dispatch Control')
    
    if not options.disable_phidget:
        def phidget_DI_changed(event):
            if event.index != 0:
                return
            if event.state:
                # TF bank is charged
                ctrl.fire()
                
        interfaceKit = InterfaceKit()
        interfaceKit.setOnInputChangeHandler(phidget_DI_changed)
        interfaceKit.openPhidget(273609)
        interfaceKit.waitForAttach(10000)
        atexit.register(interfaceKit.closePhidget)
        
    gtk.main()
    
if __name__ ==  '__main__':
    main(sys.argv[1:])
