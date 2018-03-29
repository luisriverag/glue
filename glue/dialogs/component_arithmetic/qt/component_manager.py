from __future__ import absolute_import, division, print_function

import os
from collections import defaultdict, Counter

from qtpy import QtWidgets, QtGui, QtCore
from qtpy.QtCore import Qt

from glue.core import ComponentID
from glue.core.parse import ParsedComponentLink, ParsedCommand
from glue.utils.qt import load_ui
from glue.core.message import NumericalDataChangedMessage

from glue.dialogs.component_arithmetic.qt.equation_editor import EquationEditorDialog

__all__ = ['ArithmeticEditorWidget']


# TODO: move the following class somewhere more general

class ComponentTreeWidget(QtWidgets.QTreeWidget):

    order_changed = QtCore.Signal()

    def select_cid(self, cid):
        for item in self:
            if item.data(0, Qt.UserRole) is cid:
                self.select_item(item)
                return
        raise ValueError("Could not find find cid {0} in list".format(cid))

    def select_item(self, item):
        self.selection = self.selectionModel()
        self.selection.select(QtCore.QItemSelection(self.indexFromItem(item, 0),
                                                    self.indexFromItem(item, self.columnCount() - 1)),
                              QtCore.QItemSelectionModel.ClearAndSelect)

    @property
    def selected_item(self):
        items = self.selectedItems()
        return items[0] if len(items) == 1 else None

    @property
    def selected_cid(self):
        selected = self.selected_item
        return None if selected is None else selected.data(0, Qt.UserRole)

    def add_cid_and_label(self, cid, columns):
        item = QtWidgets.QTreeWidgetItem(self.invisibleRootItem(), columns)
        item.setData(0, Qt.UserRole, cid)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setFlags(item.flags() ^ Qt.ItemIsDropEnabled)

    def __iter__(self):
        root = self.invisibleRootItem()
        for idx in range(root.childCount()):
            yield root.child(idx)

    def __len__(self):
        return self.invisibleRootItem().childCount()

    def dropEvent(self, event):
        selected = self.selected_item
        super(ComponentTreeWidget, self).dropEvent(event)
        self.select_item(selected)
        self.order_changed.emit()

    def mousePressEvent(self, event):
        self.clearSelection()
        super(ComponentTreeWidget, self).mousePressEvent(event)


class ArithmeticEditorWidget(QtWidgets.QDialog):

    def __init__(self, data_collection=None, parent=None):

        super(ArithmeticEditorWidget, self).__init__(parent=parent)

        self.ui = load_ui('component_manager.ui', self,
                          directory=os.path.dirname(__file__))

        self.list = self.ui.list_derived_components

        self.data_collection = data_collection

        self._components_derived = defaultdict(list)
        self._components_other = defaultdict(list)
        self._state = defaultdict(dict)

        for data in data_collection:

            # First find all derived components (only ones based on arithmetic
            # expressions)

            self._components_derived[data] = []

            for cid in data.derived_components:
                comp = data.get_component(cid)
                if isinstance(comp.link, ParsedComponentLink):
                    comp_state = {}
                    comp_state['cid'] = cid
                    comp_state['label'] = cid.label
                    comp_state['equation'] = comp.link._parsed
                    self._state[data][cid] = comp_state
                    self._components_derived[data].append(cid)

            # Keep track of all other components

            self._components_other[data] = []

            for cid in data.components:
                if cid not in self._components_derived[data]:
                    self._components_other[data].append(cid)

        # Populate data combo
        for data in self.data_collection:
            self.ui.combosel_data.addItem(data.label, userData=data)

        self.ui.combosel_data.setCurrentIndex(0)
        self.ui.combosel_data.currentIndexChanged.connect(self._update_component_lists)
        self._update_component_lists()

        self.ui.button_add_derived.clicked.connect(self._add_derived_component)
        self.ui.button_edit_derived.clicked.connect(self._edit_derived_component)
        self.ui.button_remove_derived.clicked.connect(self._remove_derived_component)

        self.ui.list_derived_components.itemSelectionChanged.connect(self._update_selection_derived)

        self._update_selection_derived()

        self.ui.list_derived_components.itemChanged.connect(self._update_state)
        self.ui.list_derived_components.order_changed.connect(self._update_state)

        self.ui.button_ok.clicked.connect(self.accept)
        self.ui.button_cancel.clicked.connect(self.reject)

    def _update_selection_derived(self):
        enabled = self.list.selected_cid is not None
        self.button_edit_derived.setEnabled(enabled)
        self.button_remove_derived.setEnabled(enabled)

    @property
    def data(self):
        try:
            return self.ui.combosel_data.currentData()
        except AttributeError:  # PyQt4
            return self.ui.combosel_data.itemData(self.ui.combosel_data.currentIndex())

    def _update_component_lists(self, *args):

        # This gets called when the data is changed and we need to update the
        # components shown in the lists.

        self.list.blockSignals(True)

        mapping = {}
        for cid in self.data.components:
            mapping[cid] = cid.label

        self.list.clear()
        for cid in self._components_derived[self.data]:
            label = self._state[self.data][cid]['label']
            if self._state[self.data][cid]['equation'] is None:
                expression = ''
            else:
                expression = self._state[self.data][cid]['equation'].render(mapping)
            self.list.add_cid_and_label(cid, [label, expression])

        self.list.blockSignals(False)

        self._validate()

    def _validate(self):

        # Construct a list of all labels for the current dataset so that
        # we can check which ones are duplicates
        labels = [c.label for c in self._components_other[self.data]]
        labels.extend([c['label'] for c in self._state[self.data].values()])
        if len(labels) == 0:
            return
        label_count = Counter(labels)

        # It's possible that the duplicates are entirely for components not
        # shown in this editor, so we keep track here of whether an invalid
        # component has been found.
        invalid = False

        if label_count.most_common(1)[0][1] > 1:

            # If we are here, there are duplicates somewhere in the list
            # of components.

            brush_red = QtGui.QBrush(Qt.red)
            brush_black = QtGui.QBrush(Qt.black)

            self.list.blockSignals(True)

            for item in self.list:
                label = item.text(0)
                if label_count[label] > 1:
                    item.setForeground(0, brush_red)
                    invalid = True
                else:
                    item.setForeground(0, brush_black)

            self.list.blockSignals(False)

        if invalid:
            self.ui.label_status.setStyleSheet('color: red')
            self.ui.label_status.setText('Error: some components have duplicate names')
            self.ui.button_ok.setEnabled(False)
            self.ui.combosel_data.setEnabled(False)
        else:
            self.ui.label_status.setStyleSheet('')
            self.ui.label_status.setText('')
            self.ui.button_ok.setEnabled(True)
            self.ui.combosel_data.setEnabled(True)

    def _update_state(self, *args):
        self._components_derived[self.data] = []
        for item in self.list:
            cid = item.data(0, Qt.UserRole)
            self._state[self.data][cid]['label'] = item.text(0)
            self._components_derived[self.data].append(cid)
        self._update_component_lists()

    def _remove_derived_component(self, *args):
        cid = self.list.selected_cid
        if cid is not None:
            self._components_derived[self.data].remove(cid)
            self._state[self.data].pop(cid)
            self._update_component_lists()

    def _add_derived_component(self, *args):

        comp_state = {}
        comp_state['cid'] = ComponentID('')
        comp_state['label'] = ''
        comp_state['equation'] = None

        self._components_derived[self.data].append(comp_state['cid'])
        self._state[self.data][comp_state['cid']] = comp_state

        self._update_component_lists()

        self.list.select_cid(comp_state['cid'])

        result = self._edit_derived_component()

        if not result:  # user cancelled
            self._components_derived[self.data].remove(comp_state['cid'])
            self._state[self.data].pop(comp_state['cid'])
            self._update_component_lists()

    def _edit_derived_component(self, event=None):

        derived_item = self.list.selected_item

        if derived_item is None:
            return False

        derived_cid = self.list.selected_cid

        # Note, we put the pixel/world components last as it's most likely the
        # user wants to use one of the main components.
        mapping = {}
        references = {}
        for cid in (self.data.main_components +
                    self.data.pixel_component_ids +
                    self.data.world_component_ids):
            if cid is not derived_cid:
                mapping[cid] = cid.label
                references[cid.label] = cid

        label = self._state[self.data][derived_cid]['label']

        if self._state[self.data][derived_cid]['equation'] is None:
            equation = None
        else:
            equation = self._state[self.data][derived_cid]['equation'].render(mapping)

        dialog = EquationEditorDialog(label=label, equation=equation, references=references, parent=self)
        dialog.setWindowFlags(self.windowFlags() | Qt.Window)
        dialog.setFocus()
        dialog.raise_()
        dialog.exec_()

        if dialog.final_expression is None:
            return False

        name, equation = dialog.get_final_label_and_parsed_command()
        self._state[self.data][derived_cid]['label'] = name
        self._state[self.data][derived_cid]['equation'] = equation
        derived_item.setText(0, name)

        return True

    def accept(self):

        for data in self._components_derived:

            cids_derived = self._components_derived[data]
            cids_other = self._components_other[data]
            cids_all = cids_derived + cids_other
            cids_existing = data.components
            components = dict((cid.uuid, cid) for cid in data.components)

            # First deal with renaming of components
            for cid_new in cids_derived:
                label = self._state[data][cid_new]['label']
                if label != cid_new.label:
                    cid_new.label = label

            # Second deal with the renaming of components
            for cid_old in cids_existing:
                if not any(cid_old is cid_new for cid_new in cids_all):
                    data.remove_component(cid_old)

            # Third, update/add arithmetic expressions as needed
            for cid_new in cids_derived:
                if any(cid_new is cid_old for cid_old in cids_existing):
                    comp = data.get_component(cid_new)
                    if comp.link._parsed._cmd != self._state[data][cid_new]['equation']._cmd:
                        comp.link._parsed._cmd = self._state[data][cid_new]['equation']._cmd
                        comp.link._parsed._references = components
                        if data.hub:
                            msg = NumericalDataChangedMessage(data)
                            data.hub.broadcast(msg)
                else:
                    pc = ParsedCommand(self._state[data][cid_new]['equation']._cmd, components)
                    link = ParsedComponentLink(cid_new, pc)
                    data.add_component_link(link)

            # Findally, reorder components
            data.reorder_components(cids_all)

        super(ArithmeticEditorWidget, self).accept()


if __name__ == "__main__":  # pragma: nocover

    from glue.utils.qt import get_qapp
    app = get_qapp()

    import numpy as np

    from glue.core.data import Data
    from glue.core.data_collection import DataCollection

    x = np.random.random((5, 5))
    y = x * 3
    dc = DataCollection()
    dc.append(Data(label='test1', x=x, y=y))
    dc.append(Data(label='test2', a=x, b=y))

    widget = ArithmeticEditorWidget(dc)
    widget.exec_()
