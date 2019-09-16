from pathlib import Path
from .skill import run_skill
from fault.user_cfg import FaultConfig


CREATE_LABEL = '''\
dbCreateLabel({cell_view} list("{layer}" "{purpose}") list({x} {y}) "{text}" "{justify}" "{orient}" "{font}" {height})'''  # noqa


GET_LABELS = '''\
fp = outfile("{file_name}" "w")
cv = dbOpenCellViewByType("{lib}" "{cell}" "{view}" "maskLayout" "r")
foreach(shape cv~>shapes
    if(shape~>objType == "label" then
        fprintf(fp, "%L, %L, %L, %L, %L, %L, %L\\n", shape~>lpp, shape~>xy, shape~>theLabel, shape~>justify, shape~>orient, shape~>font, shape~>height)
    )
)'''  # noqa


class LayoutLabel:
    def __init__(self, layer, purpose, x, y, text, justify, orient,
                 font, height):
        self.layer = layer
        self.purpose = purpose
        self.x = x
        self.y = y
        self.text = text
        self.justify = justify
        self.orient = orient
        self.font = font
        self.height = height

    def __str__(self):
        return f'LayoutLabel("{self.text}")'

    def create_cmd(self, cell_view):
        # return the label
        return CREATE_LABEL.format(
            cell_view=cell_view,
            layer=self.layer,
            purpose=self.purpose,
            x=self.x,
            y=self.y,
            text=self.text,
            justify=self.justify,
            orient=self.orient,
            font=self.font,
            height=self.height
        )

    @staticmethod
    def from_string(s):
        tokens = [tok.strip() for tok in s.split(',')]
        lpp = tokens[0][1:-1].split()
        xy = tokens[1][1:-1].split()
        layer = lpp[0].strip()[1:-1]
        purpose = lpp[1].strip()[1:-1]
        x = float(xy[0].strip())
        y = float(xy[1].strip())
        text = tokens[2][1:-1]
        justify = tokens[3][1:-1]
        orient = tokens[4][1:-1]
        font = tokens[5][1:-1]
        height = float(tokens[6])
        return LayoutLabel(layer=layer, purpose=purpose, x=x, y=y, text=text,
                           justify=justify, orient=orient, font=font,
                           height=height)


def get_labels(lib, cell, view, cds_lib=None, cwd=None):
    # set defaults
    if cwd is None:
        cwd = FaultConfig.cwd
    if cds_lib is None:
        cds_lib = FaultConfig.cds_lib

    # run skill code to get label locations
    lfile = Path(cwd).resolve() / 'labels.txt'
    skill_cmds = GET_LABELS.format(
        file_name=lfile,
        lib=lib,
        cell=cell,
        view=view
    )
    run_skill(skill_cmds, cds_lib=cds_lib, cwd=cwd)

    # parse results
    labels = []
    with open(lfile, 'r') as f:
        for line in f:
            labels += [LayoutLabel.from_string(line)]

    # return list of labels
    return labels